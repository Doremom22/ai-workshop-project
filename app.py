import os
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from postgrest import APIError
from supabase import Client, create_client

load_dotenv()

app = Flask(__name__)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_PUBLISHABLE_KEY")
supabase: Client | None = (
    create_client(supabase_url, supabase_key) if supabase_url and supabase_key else None
)


def database():
    if supabase is None:
        return None, (jsonify(error="Supabase is not configured"), 503)
    return supabase, None


def valid_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def db_error(error):
    return jsonify(error="Database request failed", details=getattr(error, "message", str(error))), 400


@app.get("/")
def index():
    return jsonify(message="Events API", endpoints=[
        "GET /api/events",
        "GET /api/events/<id>",
        "POST /api/registrations",
        "GET /api/me/registrations?user_id=<uuid>",
        "GET /api/events/<id>/registrations",
    ])


@app.get("/api/events")
def list_events():
    client, error = database()
    if error:
        return error
    try:
        query = client.table("events").select("*")
        if request.args.get("status"):
            query = query.eq("status", request.args["status"])
        result = query.execute()
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


@app.get("/api/events/<event_id>")
def get_event(event_id):
    event_id = valid_uuid(event_id)
    if not event_id:
        return jsonify(error="Invalid event id"), 400
    client, error = database()
    if error:
        return error
    try:
        result = client.table("events").select("*").eq("id", event_id).maybe_single().execute()
        if not result.data:
            return jsonify(error="Event not found"), 404
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


@app.post("/api/registrations")
def create_registration():
    body = request.get_json(silent=True) or {}
    user_id, event_id = valid_uuid(body.get("user_id")), valid_uuid(body.get("event_id"))
    if not user_id or not event_id:
        return jsonify(error="user_id and event_id must be valid UUIDs"), 400
    client, error = database()
    if error:
        return error
    try:
        event_result = client.table("events").select("id,capacity").eq("id", event_id).maybe_single().execute()
        if not event_result.data:
            return jsonify(error="Event not found"), 404
        user_result = client.table("users").select("id").eq("id", user_id).maybe_single().execute()
        if not user_result.data:
            return jsonify(error="User not found"), 404
        existing = client.table("registrations").select("id").eq("event_id", event_id).eq("user_id", user_id).maybe_single().execute()
        if existing.data:
            return jsonify(error="User is already registered for this event"), 409
        capacity = event_result.data.get("capacity")
        if capacity is not None:
            count = client.table("registrations").select("id", count="exact").eq("event_id", event_id).execute()
            if count.count is not None and count.count >= capacity:
                return jsonify(error="Event is at capacity"), 409
        result = client.table("registrations").insert({"user_id": user_id, "event_id": event_id}).execute()
        return jsonify(result.data[0]), 201
    except APIError as exc:
        # Also covers a concurrent duplicate insert rejected by a database constraint.
        if getattr(exc, "code", None) == "23505":
            return jsonify(error="User is already registered for this event"), 409
        return db_error(exc)


@app.get("/api/me/registrations")
def my_registrations():
    user_id = valid_uuid(request.args.get("user_id"))
    if not user_id:
        return jsonify(error="A valid user_id query parameter is required"), 400
    client, error = database()
    if error:
        return error
    try:
        result = client.table("registrations").select("*, events(*)").eq("user_id", user_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


@app.get("/api/events/<event_id>/registrations")
def event_registrations(event_id):
    event_id = valid_uuid(event_id)
    if not event_id:
        return jsonify(error="Invalid event id"), 400
    client, error = database()
    if error:
        return error
    try:
        event_result = client.table("events").select("id").eq("id", event_id).maybe_single().execute()
        if not event_result.data:
            return jsonify(error="Event not found"), 404
        result = client.table("registrations").select("*, users(id,email,role)").eq("event_id", event_id).execute()
        return jsonify(result.data)
    except APIError as exc:
        return db_error(exc)


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
