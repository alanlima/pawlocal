from pawlocal.application.ports import CommunityRepository
from pawlocal.observability import application_span, mark_rejected


class CommunityCommands:
    def __init__(self, repository: CommunityRepository):
        self.repository = repository

    def favourites(self, subject: str):
        with application_span(
            "favourites.list", {"pawlocal.operation": "favourite_list"}
        ):
            return self.repository.list_favourites(subject)

    def add_favourite(self, subject: str, place_id) -> bool:
        with application_span(
            "favourites.add", {"pawlocal.operation": "favourite_add"}
        ) as span:
            added = self.repository.add_favourite(subject, place_id)
            if not added:
                mark_rejected(span, "favourite_place_unavailable")
            else:
                span.set_attribute("pawlocal.outcome", "success")
            return added

    def remove_favourite(self, subject: str, place_id) -> None:
        with application_span(
            "favourites.remove", {"pawlocal.operation": "favourite_remove"}
        ):
            self.repository.remove_favourite(subject, place_id)

    def contribute(self, subject: str, values: dict):
        with application_span(
            "contributions.submit", {"pawlocal.operation": "contribution"}
        ) as span:
            contribution = self.repository.submit_contribution(subject, values)
            if contribution is None:
                mark_rejected(span, "contribution_place_unavailable")
            else:
                span.set_attribute("pawlocal.outcome", "success")
            return contribution

    def report(self, subject: str, values: dict) -> bool:
        with application_span(
            "reports.submit", {"pawlocal.operation": "report"}
        ) as span:
            submitted = self.repository.submit_report(subject, values)
            if not submitted:
                mark_rejected(span, "report_target_unavailable")
            else:
                span.set_attribute("pawlocal.outcome", "success")
            return submitted
