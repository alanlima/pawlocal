from pawlocal.application.ports import CommunityRepository
from pawlocal.observability import application_span


class CommunityCommands:
    def __init__(self, repository: CommunityRepository):
        self.repository = repository

    def favourites(self, subject: str):
        with application_span("favourites.list", {"pawlocal.operation": "favourite_list"}):
            return self.repository.list_favourites(subject)

    def add_favourite(self, subject: str, place_id) -> bool:
        with application_span("favourites.add", {"pawlocal.operation": "favourite_add"}):
            return self.repository.add_favourite(subject, place_id)

    def remove_favourite(self, subject: str, place_id) -> None:
        with application_span("favourites.remove", {"pawlocal.operation": "favourite_remove"}):
            self.repository.remove_favourite(subject, place_id)

    def contribute(self, subject: str, values: dict):
        with application_span("contributions.submit", {"pawlocal.operation": "contribution"}):
            return self.repository.submit_contribution(subject, values)

    def report(self, subject: str, values: dict) -> bool:
        with application_span("reports.submit", {"pawlocal.operation": "report"}):
            return self.repository.submit_report(subject, values)
