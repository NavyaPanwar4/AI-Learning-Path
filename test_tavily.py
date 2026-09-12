import sys
import os
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.web_search_service import web_search_service
from app.services.roadmap_service import roadmap_service

print("Testing direct web search:")

results = web_search_service.search_courses(["React Native", "Firebase"])

for r in results:
    print(f"Course Title: {r['title']}")
    print(f"URL: {r['url']}")
    print(f"Content: {r['content']}\n")

print("Web search works!")