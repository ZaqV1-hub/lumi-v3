"""Google Calendar REST, com OAuth do próprio serviço. Não usa conectores do chat."""
from functools import lru_cache
import threading
from urllib.parse import quote
import httpx

SCOPES = ["https://www.googleapis.com/auth/calendar.events",
          "https://www.googleapis.com/auth/calendar.events.freebusy"]
BASE = "https://www.googleapis.com/calendar/v3"
TOKEN_LOCK = threading.Lock()


@lru_cache(maxsize=16)
def credentials_for(path):
    from google.oauth2.credentials import Credentials
    return Credentials.from_authorized_user_file(path, SCOPES)


class GoogleCalendar:
    def __init__(self, config):
        self.config = config

    def request(self, method, path, **kwargs):
        from google.auth.transport.requests import Request
        with TOKEN_LOCK:
            credentials = credentials_for(self.config.token_file)
            if not credentials.valid:
                transport = Request()
                credentials.refresh(lambda **kwargs: transport(**{**kwargs, "timeout": 10}))
            access_token = credentials.token
        # Refresh tokens remain in the original private file; no tokens in logs/returns.
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + access_token
        return httpx.request(method, BASE + path, headers=headers,
                             timeout=10, follow_redirects=False, **kwargs)

    @property
    def path(self):
        return "/calendars/" + quote(self.config.calendar_id, safe="") + "/events"

    def busy(self, start, end):
        response = self.request("POST", "/freeBusy", json={"timeMin": start.isoformat(), "timeMax": end.isoformat(),
            "timeZone": self.config.timezone, "items": [{"id": self.config.calendar_id}]})
        response.raise_for_status()
        calendar = response.json().get("calendars", {}).get(self.config.calendar_id)
        if calendar is None or calendar.get("errors"):
            raise RuntimeError("Disponibilidade não confirmada")
        return calendar.get("busy", [])

    def get(self, event_id):
        response = self.request("GET", self.path + "/" + event_id)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def participants(self, booking, emails, operation_id, resend):
        event = self.get(booking["event"])
        if event is None:
            raise RuntimeError("Evento não encontrado")
        public_event(event, booking)
        if event.get("attendeesOmitted") or not event.get("etag"):
            raise RuntimeError("Participantes incompletos")
        private = event.get("extendedProperties", {}).get("private", {})
        attendees = event.get("attendees", [])
        known = {a["email"].lower() for a in attendees if a.get("email")}
        additions = sorted(set(emails) - known)
        if not additions and not resend:
            return event, False
        # Arrays are replaced by Calendar PATCH: preserve every existing guest and RSVP.
        fields = {"email", "displayName", "optional", "resource", "responseStatus", "comment", "additionalGuests"}
        merged = [{k:v for k,v in a.items() if k in fields} for a in attendees]
        merged.extend({"email":email} for email in additions)
        response = self.request("PATCH", self.path + "/" + booking["event"],
            headers={"If-Match": event["etag"]}, params={"sendUpdates":"all" if self.config.send_invites else "none", "conferenceDataVersion":1},
            json={"attendees":merged,"extendedProperties":{"private":{**private,"lumi_participants_op":operation_id}}})
        response.raise_for_status()
        return response.json(), self.config.send_invites

    def description(self, booking, text, operation_id):
        event = self.get(booking["event"])
        if event is None:
            raise RuntimeError("Evento não encontrado")
        public_event(event, booking)
        if not event.get("etag"):
            raise RuntimeError("Versão do evento ausente")
        private = event.get("extendedProperties", {}).get("private", {})
        response = self.request("PATCH", self.path + "/" + booking["event"],
            headers={"If-Match": event["etag"]}, params={"sendUpdates":"none"},
            json={"description":text,"extendedProperties":{"private":{**private,"lumi_description_op":operation_id}}})
        response.raise_for_status()
        return response.json()

    def create(self, booking):
        data = {"id": booking["event"], "summary": self.config.title,
            "description": "Participante: " + booking["name"] + "\nAssunto: " + booking["topic"],
            "start": {"dateTime": booking["start"], "timeZone": self.config.timezone},
            "end": {"dateTime": booking["end"], "timeZone": self.config.timezone},
            "attendees": [{"email": booking["email"], "displayName": booking["name"]}],
            "extendedProperties": {"private": {"lumi_booking": booking["id"]}}}
        if self.config.create_meet:
            data["conferenceData"] = {"createRequest": {"requestId": booking["event"],
                "conferenceSolutionKey": {"type": "hangoutsMeet"}}}
        response = self.request("POST", self.path, params={"sendUpdates": "all" if self.config.send_invites else "none",
            "conferenceDataVersion": 1 if self.config.create_meet else 0}, json=data)
        if response.status_code == 409:
            event = self.get(booking["event"])
            if event is None:
                raise RuntimeError("Resultado não confirmado")
            return event
        response.raise_for_status()
        return response.json()


def public_event(event, booking):
    # Never trust a colliding event ID or a cancelled event as a successful write.
    if (event.get("id") != booking["event"] or event.get("status") != "confirmed" or
        event.get("extendedProperties", {}).get("private", {}).get("lumi_booking") != booking["id"]):
        raise RuntimeError("Evento não corresponde ao agendamento")
    result = {"status": "confirmed", "start": event.get("start", {}).get("dateTime", booking["start"]),
              "end": event.get("end", {}).get("dateTime", booking["end"])}
    for field, source, host in [("calendar_url", "htmlLink", "calendar.google.com"), ("meet_url", "hangoutLink", "meet.google.com")]:
        from urllib.parse import urlsplit
        value = event.get(source)
        if value and urlsplit(value).scheme == "https" and (urlsplit(value).hostname == host or
            (field == "calendar_url" and urlsplit(value).hostname == "www.google.com" and urlsplit(value).path.startswith("/calendar/"))):
            result[field] = value
    return result
