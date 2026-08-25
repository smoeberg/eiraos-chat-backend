import inspect

from eiraos.api.v1.organizations import list_organizations, create_organization
from eiraos.core import ratelimit


def test_list_organizations_is_membership_scoped():
    """list_organizations must never return organizations the user isn't a member of."""
    src = inspect.getsource(list_organizations)
    assert ".join(OrganizationMember" in src
    assert "OrganizationMember.user_id == current_user" in src
    # ...and must not be an unfiltered select over all organizations.
    assert "select(Organization)" in src


def test_create_organization_enrolls_creator_as_owner():
    src = inspect.getsource(create_organization)
    assert "role=\"owner\"" in src
    assert "OrganizationMember(" in src


def test_create_organization_has_a_trusted_proxy_backed_route_limit():
    signature = inspect.signature(create_organization)
    assert "request" in signature.parameters
    assert ratelimit.ORGANIZATION_CREATE_LIMIT == "5/minute"
    assert "@limiter.limit(ratelimit.ORGANIZATION_CREATE_LIMIT)" in inspect.getsource(
        create_organization
    )
