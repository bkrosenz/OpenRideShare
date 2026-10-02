from __future__ import annotations

from urllib.parse import urlparse

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput

from client.api import RideShareAPI, open_android_uri


class RideShareRoot(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", padding=dp(20), spacing=dp(10), **kwargs)
        self.api = RideShareAPI()
        self.driver_available = False
        self.add_widget(Label(text="OPEN RIDESHARE", font_size="24sp", size_hint_y=None, height=dp(42), color=(0.12, 0.25, 0.22, 1)))
        self.status = Label(text="Invitation-only community rides", size_hint_y=None, height=dp(34))
        self.add_widget(self.status)
        self.form = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        self.form.bind(minimum_height=self.form.setter("height"))
        scroll = ScrollView(do_scroll_x=False)
        scroll.add_widget(self.form)
        self.add_widget(scroll)
        self.endpoint = self._input("HTTPS API endpoint", text=self.api.base_url)
        self.username = self._input("Username")
        self.password = self._input("Password", password=True)
        self.invitation = self._input("Invitation code")
        self.form.add_widget(self._button("Sign in", self.sign_in))
        self.form.add_widget(self._button("Create invited account", self.register))
        self.form.add_widget(Label(text="RIDE DETAILS", size_hint_y=None, height=dp(34), color=(0.12, 0.25, 0.22, 1)))
        self.pickup = self._input("Pickup latitude, longitude")
        self.dropoff = self._input("Destination latitude, longitude")
        self.tip = self._input("Tip in dollars (optional)", text="0.00", input_filter="float")
        self.uber = self._provider_choice("Use Uber if no community driver is available")
        self.lyft = self._provider_choice("Use Lyft if no community driver is available")
        self.form.add_widget(self._button("Request ride", self.request_ride))
        self.form.add_widget(self._button("Toggle driver availability", self.toggle_driver))
        self.form.add_widget(self._button("Check assigned ride requests", self.refresh_assigned_rides))

    def _input(self, hint: str, **kwargs) -> TextInput:
        field = TextInput(hint_text=hint, multiline=False, size_hint_y=None, height=dp(46), **kwargs)
        self.form.add_widget(field)
        return field

    def _button(self, text: str, callback) -> Button:
        button = Button(text=text, size_hint_y=None, height=dp(48), background_normal="", background_color=(0.12, 0.36, 0.30, 1), color=(1, 1, 1, 1))
        button.bind(on_press=lambda _: callback())
        return button

    def _provider_choice(self, text: str) -> CheckBox:
        row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(8))
        checkbox = CheckBox(size_hint_x=None, width=dp(42))
        label = Label(text=text, halign="left", valign="middle")
        label.bind(size=lambda widget, size: setattr(widget, "text_size", size))
        row.add_widget(checkbox)
        row.add_widget(label)
        self.form.add_widget(row)
        return checkbox

    def _show_message(self, message: str):
        self.status.text = message

    def _coordinates(self, field: TextInput) -> tuple[float, float]:
        parts = [float(part.strip()) for part in field.text.split(",")]
        if len(parts) != 2 or not -90 <= parts[0] <= 90 or not -180 <= parts[1] <= 180:
            raise ValueError("Enter latitude, longitude using valid coordinates.")
        return parts[0], parts[1]

    def _sync_endpoint(self):
        endpoint = self.endpoint.text.strip().rstrip("/")
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Use a valid HTTPS API endpoint.")
        self.api.base_url = endpoint

    def sign_in(self):
        try:
            self._sync_endpoint()
            self.api.login(self.username.text.strip(), self.password.text)
            self._show_message("Signed in. Your session stays on this device only.")
        except Exception:
            self._show_message("Sign-in failed. Check your credentials and network.")

    def register(self):
        try:
            self._sync_endpoint()
            self.api.register(self.username.text.strip(), self.password.text, self.invitation.text.strip())
            self._show_message("Account created. Sign in to continue.")
        except Exception:
            self._show_message("Account creation failed. Check your invitation and password length.")

    def request_ride(self):
        try:
            self._sync_endpoint()
            providers = (["uber"] if self.uber.active else []) + (["lyft"] if self.lyft.active else [])
            result = self.api.request_ride(
                self._coordinates(self.pickup),
                self._coordinates(self.dropoff),
                round(float(self.tip.text or "0") * 100),
                providers,
            )
            self._show_message(f"{result['status'].title()} · ${result['fare_cents'] / 100:.2f} before tip")
            if result.get("status") == "unmatched":
                packages = {"uber": "com.ubercab", "lyft": "me.lyft.android"}
                opened = any(open_android_uri(uri, packages[provider]) for provider, uri in result.get("handoff_options", {}).items())
                if not opened and result.get("handoff_options"):
                    self._show_message("No opted-in rideshare app is installed. Your request remains unmatched.")
            elif result.get("payment_uri"):
                self._show_payment(result)
        except ValueError as error:
            self._show_message(str(error))
        except Exception:
            self._show_message("Ride request failed. Please try again.")

    def _show_payment(self, result: dict):
        popup = Popup(title="Community ride", size_hint=(0.88, None), height=dp(180))
        content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(8))
        content.add_widget(Label(text=f"Fare ${result['fare_cents'] / 100:.2f} · tip ${result['tip_cents'] / 100:.2f}"))
        pay = Button(text="Open Venmo", size_hint_y=None, height=dp(46))
        pay.bind(on_press=lambda _: (open_android_uri(result["payment_uri"], "com.venmo"), popup.dismiss()))
        content.add_widget(pay)
        popup.content = content
        popup.open()

    def toggle_driver(self):
        try:
            self._sync_endpoint()
            latitude, longitude = self._coordinates(self.pickup)
            self.driver_available = not self.driver_available
            self.api.update_driver(latitude, longitude, self.driver_available)
            state = "available" if self.driver_available else "offline"
            self._show_message(f"Driver status: {state} at the pickup location.")
        except Exception:
            self._show_message("Driver availability update failed. Sign in and set a valid location.")

    def refresh_assigned_rides(self):
        try:
            self._sync_endpoint()
            rides = self.api.assigned_rides()
            self._show_message(f"{len(rides)} ride request(s) assigned to you.")
            if rides:
                ride = rides[0]
                self._show_message(f"Pickup {ride['pickup']} · destination {ride['dropoff']} · ${ride['fare_cents'] / 100:.2f}")
        except Exception:
            self._show_message("Could not load assigned rides. Sign in and try again.")


class OpenRideShareApp(App):
    def build(self):
        self.title = "OpenRideShare"
        return RideShareRoot()


if __name__ == "__main__":
    OpenRideShareApp().run()