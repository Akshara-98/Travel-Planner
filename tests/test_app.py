import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from travel_planner.db import init_db


class TravelPlannerAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.database_directory = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.database_directory.name) / "travel_planner_test.db"
        app.config["DB_PATH"] = str(cls.database_path)
        init_db(str(cls.database_path))

    @classmethod
    def tearDownClass(cls):
        cls.database_directory.cleanup()

    def setUp(self):
        self.client = app.test_client()

    def test_home_page_loads(self):
        response = self.client.get("/")
        try:
            page = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Agentic AI Travel Planner", page)
            self.assertIn("<style>", page)
            self.assertIn("<script>", page)
            self.assertNotIn("{{ url_for", page)
        finally:
            response.close()

    def test_live_server_origin_can_call_api(self):
        response = self.client.options(
            "/api/travel-plan",
            headers={
                "Origin": "http://127.0.0.1:5500",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5500"
        )
        self.assertIn("POST", response.headers["Access-Control-Allow-Methods"])

    def test_non_loopback_origin_cannot_call_api(self):
        response = self.client.get(
            "/health", headers={"Origin": "https://example.com"}
        )
        self.assertNotIn("Access-Control-Allow-Origin", response.headers)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")

    def test_wikipedia_request_identifies_the_app(self):
        from travel_planner.agent import fetch_wikipedia

        mock_response = unittest.mock.Mock()
        mock_response.json.return_value = {
            "query": {
                "pages": [
                    {"title": "Paris", "extract": "Paris is the capital of France."}
                ]
            }
        }

        with patch("travel_planner.agent.requests.get", return_value=mock_response) as get:
            with app.app_context():
                result = fetch_wikipedia("Paris")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["page_title"], "Paris")
        self.assertEqual(
            get.call_args.kwargs["headers"]["User-Agent"],
            app.config["WIKIPEDIA_USER_AGENT"],
        )

    def test_submit_travel_plan_without_email(self):
        payload = {
            "destination": "Paris",
            "start_date": "2027-03-10",
            "end_date": "2027-03-15",
            "travelers": "2",
            "budget": "$1800",
            "interests": "Food, museums, parks",
            "starting_location": "London",
            "additional_instructions": "Make it family-friendly",
            "execution_id": "test-plan-without-email",
        }
        weather = {"status": "completed", "summary": "Mild and sunny."}
        wikipedia = {"status": "completed", "summary": "Paris is the capital of France."}
        generated_plan = {"itinerary": []}

        with patch("travel_planner.agent.fetch_weather", return_value=weather), patch(
            "travel_planner.agent.fetch_wikipedia", return_value=wikipedia
        ), patch("travel_planner.agent.call_gemini", return_value=generated_plan):
            response = self.client.post("/api/travel-plan", data=payload)
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            execution_id = response.get_json()["execution_id"]

            plan = None
            for _ in range(50):
                time.sleep(0.02)
                state = self.client.get(f"/api/plans/{execution_id}")
                plan = state.get_json().get("plan")
                if plan:
                    break

        self.assertIsNotNone(plan)
        self.assertEqual(plan["email"], "")
        self.assertEqual(plan["status"], "pending_approval")

        approval = self.client.post(f"/api/plans/{execution_id}/approve")
        self.assertEqual(approval.status_code, 200)
        email_response = self.client.post(f"/api/plans/{execution_id}/email")
        self.assertEqual(email_response.status_code, 400)
        self.assertIn("email address", email_response.get_json()["error"])

    def test_execution_state_exists_before_worker_starts(self):
        payload = {
            "destination": "Paris",
            "start_date": "2027-03-10",
            "end_date": "2027-03-15",
            "execution_id": "test-sse-state-before-worker",
        }

        with patch("travel_planner.routes.threading.Thread.start"):
            response = self.client.post("/api/travel-plan", data=payload)

        self.assertEqual(response.status_code, 200)
        execution_id = response.get_json()["execution_id"]
        state_response = self.client.get(f"/api/plans/{execution_id}")
        stream_response = self.client.get(f"/api/events/{execution_id}", buffered=False)
        try:
            self.assertEqual(state_response.status_code, 200)
            self.assertEqual(state_response.get_json()["status"], "running")
            self.assertEqual(stream_response.status_code, 200)
            self.assertIn("Plan Request Accepted", next(stream_response.response).decode())
        finally:
            stream_response.close()

    def test_background_generation_error_is_reported(self):
        payload = {
            "destination": "Paris",
            "start_date": "2027-03-10",
            "end_date": "2027-03-15",
        }

        with patch("travel_planner.routes.generate_plan", side_effect=RuntimeError("test failure")):
            response = self.client.post("/api/travel-plan", data=payload)
            self.assertEqual(response.status_code, 200)
            execution_id = response.get_json()["execution_id"]

            state = None
            for _ in range(50):
                time.sleep(0.02)
                state = self.client.get(f"/api/plans/{execution_id}").get_json()
                if state["status"] == "failed":
                    break

        self.assertEqual(state["status"], "failed")
        events_response = self.client.get(f"/api/events/{execution_id}", buffered=False)
        try:
            self.assertEqual(events_response.status_code, 200)
            next(events_response.response)
            event = next(events_response.response).decode()
            self.assertIn("Plan generation failed due to a server error.", event)
        finally:
            events_response.close()

    def test_submit_travel_plan_and_approve(self):
        payload = {
            "destination": "Paris",
            "start_date": "2027-03-10",
            "end_date": "2027-03-15",
            "travelers": "2",
            "budget": "$1800",
            "interests": "Food, museums, parks",
            "starting_location": "London",
            "email": "demo@example.com",
            "additional_instructions": "Make it family-friendly",
        }

        response = self.client.post("/api/travel-plan", data=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        execution_id = response.get_json()["execution_id"]

        plan = None
        for _ in range(50):
            time.sleep(0.2)
            state = self.client.get(f"/api/plans/{execution_id}")
            if state.status_code == 200:
                plan = state.get_json().get("plan")
                if plan:
                    break

        self.assertIsNotNone(plan)
        self.assertIn("destination", plan)

        approval = self.client.post(f"/api/plans/{execution_id}/approve")
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(approval.get_json()["status"], "approved")

        save_response = self.client.post(f"/api/plans/{execution_id}/save")
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.get_json()["status"], "saved")


if __name__ == "__main__":
    unittest.main()
