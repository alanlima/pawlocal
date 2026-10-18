from pawlocal.application.ports import CommunityRepository


class CommunityCommands:
    def __init__(self, repository: CommunityRepository):
        self.repository = repository

    def favourites(self, subject: str):
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "favourites.list", attributes={"pawlocal.operation": "favourite_list"},
            record_exception=False, set_status_on_exception=False,
        ):
            return self.repository.list_favourites(subject)

    def add_favourite(self, subject: str, place_id) -> bool:
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "favourites.add", attributes={"pawlocal.operation": "favourite_add"},
            record_exception=False, set_status_on_exception=False,
        ):
            return self.repository.add_favourite(subject, place_id)

    def remove_favourite(self, subject: str, place_id) -> None:
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "favourites.remove", attributes={"pawlocal.operation": "favourite_remove"},
            record_exception=False, set_status_on_exception=False,
        ):
            self.repository.remove_favourite(subject, place_id)

    def contribute(self, subject: str, values: dict):
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "contributions.submit", attributes={"pawlocal.operation": "contribution"},
            record_exception=False, set_status_on_exception=False,
        ):
            return self.repository.submit_contribution(subject, values)

    def report(self, subject: str, values: dict) -> bool:
        with trace.get_tracer("pawlocal.application").start_as_current_span(
            "reports.submit", attributes={"pawlocal.operation": "report"},
            record_exception=False, set_status_on_exception=False,
        ):
            return self.repository.submit_report(subject, values)


from opentelemetry import trace
