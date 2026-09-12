import requests
import json

def test_flow():
    base = "http://localhost:8000"
    print("Registering...")
    r = requests.post(base + "/auth/register", json={
        "username": "riley2", "email": "riley2@example.com", "password": "SecurePassword123!"
    })
    print(r.status_code, r.text)
    
    print("Logging in...")
    r = requests.post(base + "/auth/login", json={
        "username": "riley2@example.com", "password": "SecurePassword123!"
    })
    print(r.status_code, r.text)
    if r.status_code != 200:
        return
    token = r.json().get("access_token")
    headers = {"Authorization": f"Bearer " + token}
    
    print("Fetching Goals...")
    goals = requests.get(base + "/users/goals", headers=headers)
    print(goals.status_code, goals.text)
    goal_id = goals.json()[0]['goal_id'] if goals.status_code == 200 and len(goals.json()) > 0 else "goal-1"
    
    print("Updating Profile...")
    r = requests.put(base + "/users/profile", json={
        "goal_id": goal_id,
        "experience_level": "beginner",
        "available_hours_per_week": 10,
        "learning_style": "Visual"
    }, headers=headers)
    print(r.status_code, r.text)
    
    print("Generating Roadmap...")
    r = requests.post(base + "/roadmap/generate-roadmap", headers=headers)
    print(r.status_code, r.text)

if __name__ == "__main__":
    test_flow()
