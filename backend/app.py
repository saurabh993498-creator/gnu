import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from postgrest import APIError
from supabase import Client, create_client

load_dotenv()
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
supabase: Client | None = create_client(url, key) if url and key else None


def client_or_error():
    if supabase is None:
        return None, (jsonify(error="Supabase is not configured"), 503)
    return supabase, None


def as_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def db_error(error):
    return jsonify(error=str(error)), 500


@app.get("/")
def index():
    return jsonify(
        name="Events API",
        status="ok",
        endpoints={
            "list_events": "GET /api/events",
            "event_details": "GET /api/events/<event_id>",
            "create_registration": "POST /api/registrations",
            "user_registrations": "GET /api/me/registrations?user_id=<user_id>",
            "event_attendees": "GET /api/events/<event_id>/registrations?organizer_id=<organizer_id>",
        },
    )


@app.get("/api/events")
def list_events():
    client, error = client_or_error()
    if error:
        return error
    try:
        query = client.table("events").select("*")
        if request.args.get("status"):
            query = query.eq("status", request.args["status"])
        return jsonify(query.execute().data)
    except APIError as exc:
        return db_error(exc)


@app.get("/api/events/<event_id>")
def get_event(event_id):
    event_id = as_uuid(event_id)
    if not event_id:
        return jsonify(error="Invalid event id"), 400
    client, error = client_or_error()
    if error:
        return error
    try:
        result = client.table("events").select("*").eq("id", event_id).maybe_single().execute()
        return (jsonify(result.data), 200) if result.data else (jsonify(error="Event not found"), 404)
    except APIError as exc:
        return db_error(exc)


@app.post("/api/registrations")
def create_registration():
    body = request.get_json(silent=True) or {}
    user_id, event_id = as_uuid(body.get("user_id")), as_uuid(body.get("event_id"))
    if not user_id or not event_id:
        return jsonify(error="user_id and event_id must be valid UUIDs"), 400
    client, error = client_or_error()
    if error:
        return error
    try:
        event = client.table("events").select("id,capacity,status").eq("id", event_id).maybe_single().execute().data
        if not event:
            return jsonify(error="Event not found"), 404
        if event["status"] != "open":
            return jsonify(error="Event is not open"), 409
        count = client.table("registrations").select("id", count="exact").eq("event_id", event_id).execute().count or 0
        if count >= event["capacity"]:
            return jsonify(error="Event is full"), 409
        result = client.table("registrations").insert({"user_id": user_id, "event_id": event_id}).execute()
        return jsonify(result.data[0]), 201
    except APIError as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return jsonify(error="Already registered"), 409
        return db_error(exc)


@app.get("/api/me/registrations")
def my_registrations():
    user_id = as_uuid(request.args.get("user_id"))
    if not user_id:
        return jsonify(error="user_id query parameter must be a UUID"), 400
    client, error = client_or_error()
    if error:
        return error
    try:
        result = client.table("registrations").select("*,events(*)").eq("user_id", user_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


@app.get("/api/events/<event_id>/registrations")
def event_registrations(event_id):
    event_id, organizer_id = as_uuid(event_id), as_uuid(request.args.get("organizer_id"))
    if not event_id or not organizer_id:
        return jsonify(error="Valid event id and organizer_id query parameter are required"), 400
    client, error = client_or_error()
    if error:
        return error
    try:
        event = client.table("events").select("organizer_id").eq("id", event_id).maybe_single().execute().data
        if not event:
            return jsonify(error="Event not found"), 404
        if event["organizer_id"] != organizer_id:
            return jsonify(error="Only the organizer may view attendees"), 403
        result = client.table("registrations").select("*,users(id,email,role)").eq("event_id", event_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


if __name__ == "__main__":
    app.run(debug=True)
