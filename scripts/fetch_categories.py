#!/usr/bin/env python3
import sys
sys.path.insert(0, '/iriswebapp')
from app.app import create_app
from app.models.cases import EventCategory

app = create_app()
with app.app_context():
    cats = EventCategory.query.all()
    for cat in cats:
        print(f"{cat.event_category_id},{cat.event_category_title}")
