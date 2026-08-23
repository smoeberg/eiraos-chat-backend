import inspect

from eiraos.api.v1.organizations import list_organizations, create_organization


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
