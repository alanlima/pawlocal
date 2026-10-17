from pawlocal.application.ports import CommunityRepository


class CommunityCommands:
    def __init__(self, repository: CommunityRepository):
        self.repository = repository

    def favourites(self, subject: str):
        return self.repository.list_favourites(subject)

    def add_favourite(self, subject: str, place_id) -> bool:
        return self.repository.add_favourite(subject, place_id)

    def remove_favourite(self, subject: str, place_id) -> None:
        self.repository.remove_favourite(subject, place_id)

    def contribute(self, subject: str, values: dict):
        return self.repository.submit_contribution(subject, values)

    def report(self, subject: str, values: dict) -> bool:
        return self.repository.submit_report(subject, values)
