from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from pawlocal.api.auth import get_current_subject
from pawlocal.api.rate_limit import enforce_write_rate_limit
from pawlocal.api.schemas import (
    ContributionInput,
    ContributionResponse,
    ErrorResponse,
    PlacePage,
    PlaceReference,
    PlaceResponse,
    PlaceSummary,
    ReportableContribution,
    ReportableContributionPage,
    ReportInput,
)
from pawlocal.application.community import CommunityCommands
from pawlocal.application.errors import DuplicateReviewError
from pawlocal.application.places import PlaceQueries, ReportableContributionQueries
from pawlocal.domain.places import PLACE_CATEGORIES, PLACE_FACILITIES
from pawlocal.infrastructure.community import CommunityRepository
from pawlocal.infrastructure.contributions import SqlAlchemyContributionRepository
from pawlocal.infrastructure.database import get_session
from pawlocal.infrastructure.places import SqlAlchemyPlaceRepository

router = APIRouter()


def get_place_queries(
    session: Annotated[Session, Depends(get_session)],
) -> PlaceQueries:
    return PlaceQueries(SqlAlchemyPlaceRepository(session))


def get_contribution_queries(
    session: Annotated[Session, Depends(get_session)],
) -> ReportableContributionQueries:
    return ReportableContributionQueries(SqlAlchemyContributionRepository(session))


def get_community_commands(
    session: Annotated[Session, Depends(get_session)],
) -> CommunityCommands:
    return CommunityCommands(CommunityRepository(session))


def _require_rate_limit(subject: Annotated[str, Depends(get_current_subject)]) -> None:
    enforce_write_rate_limit(subject)


def _summary(place) -> PlaceSummary:
    return PlaceSummary(
        id=place.id,
        name=place.name,
        category=place.category,
        area=place.area,
        average_rating=place.average_rating,
    )


@router.get(
    "/places", response_model=PlacePage, responses={400: {"model": ErrorResponse}}
)
def list_places(
    queries: Annotated[PlaceQueries, Depends(get_place_queries)],
    q: Annotated[str | None, Query(max_length=120)] = None,
    area: Annotated[str | None, Query(max_length=160)] = None,
    category: Annotated[str | None, Query()] = None,
    facilities: Annotated[list[str] | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PlacePage:
    if category is not None and category not in PLACE_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Unsupported category"},
        )
    if any(facility not in PLACE_FACILITIES for facility in facilities or []):
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Unsupported facility"},
        )
    places, total = queries.search(
        query=q,
        area=area,
        category=category,
        facilities=facilities or [],
        page=page,
        page_size=page_size,
    )
    return PlacePage(
        items=[_summary(place) for place in places],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/places/{place_id}",
    response_model=PlaceResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_place(
    place_id: UUID,
    queries: Annotated[PlaceQueries, Depends(get_place_queries)],
) -> PlaceResponse:
    place = queries.get(place_id)
    if place is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "Place not found"}
        )
    return PlaceResponse(
        id=place.id,
        name=place.name,
        category=place.category,
        area=place.area,
        average_rating=place.average_rating,
        address=place.address,
        description=place.description,
        dog_access_rules=place.dog_access_rules,
        facilities=list(place.facilities),
        source_updated_at=place.source_updated_at,
    )


@router.get(
    "/contributions/reportable",
    response_model=ReportableContributionPage,
    responses={400: {"model": ErrorResponse}},
)
def list_reportable_contributions(
    queries: Annotated[
        ReportableContributionQueries, Depends(get_contribution_queries)
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReportableContributionPage:
    items, total = queries.list(page=page, page_size=page_size)
    return ReportableContributionPage(
        items=[
            ReportableContribution(
                id=item.id,
                kind=item.kind,
                body=item.body,
                place_id=item.place_id,
                rating=item.rating,
                created_at=item.created_at,
            )
            for item in items
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get(
    "/me/favourites",
    response_model=list[PlaceSummary],
    responses={401: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def list_favourites(
    subject: Annotated[str, Depends(get_current_subject)],
    commands: Annotated[CommunityCommands, Depends(get_community_commands)],
) -> list[PlaceSummary]:
    return [_summary(place) for place in commands.favourites(subject)]


@router.put(
    "/me/favourites",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def add_favourite(
    payload: PlaceReference,
    subject: Annotated[str, Depends(get_current_subject)],
    commands: Annotated[CommunityCommands, Depends(get_community_commands)],
    _: Annotated[None, Depends(_require_rate_limit)],
) -> Response:
    if not commands.add_favourite(subject, payload.place_id):
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Place not found"},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/me/favourites/{place_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def remove_favourite(
    place_id: UUID,
    subject: Annotated[str, Depends(get_current_subject)],
    commands: Annotated[CommunityCommands, Depends(get_community_commands)],
    _: Annotated[None, Depends(_require_rate_limit)],
) -> Response:
    commands.remove_favourite(subject, place_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/contributions",
    response_model=ContributionResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def submit_contribution(
    payload: ContributionInput,
    subject: Annotated[str, Depends(get_current_subject)],
    commands: Annotated[CommunityCommands, Depends(get_community_commands)],
    _: Annotated[None, Depends(_require_rate_limit)],
) -> ContributionResponse:
    try:
        contribution = commands.contribute(subject, payload.model_dump())
    except DuplicateReviewError:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "conflict",
                "message": "A review for this place already exists",
            },
        ) from None
    if contribution is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Place is unavailable"},
        )
    return ContributionResponse(
        id=contribution.id,
        kind=contribution.kind,
        body=contribution.body,
        place_id=contribution.place_id,
        rating=contribution.rating,
        created_at=contribution.created_at,
    )


@router.post(
    "/reports",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def submit_report(
    payload: ReportInput,
    subject: Annotated[str, Depends(get_current_subject)],
    commands: Annotated[CommunityCommands, Depends(get_community_commands)],
    _: Annotated[None, Depends(_require_rate_limit)],
) -> Response:
    if not commands.report(subject, payload.model_dump()):
        raise HTTPException(
            status_code=400,
            detail={"code": "bad_request", "message": "Report target is unavailable"},
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)
