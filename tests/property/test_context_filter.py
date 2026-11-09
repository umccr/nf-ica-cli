"""Property-based tests for context-based project filtering.

Tests Property 9 from the design document using Hypothesis.
"""

from typing import List, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from nf_ica_cli.config import IcaProject, OidcAuth, Tenant
from nf_ica_cli.handlers.deploy_workflow import filter_projects_by_context


# --- Strategies ---

# Context names: simple alphanumeric labels
context_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=20,
)

# Strategy for generating a list of unique context names
context_pools = st.lists(context_names, min_size=1, max_size=10, unique=True)


# Strategy for generating an IcaProject with contexts drawn from a pool
def ica_project_strategy(context_pool: List[str]) -> st.SearchStrategy:
    """Generate an IcaProject with contexts from the given pool."""
    return st.builds(
        IcaProject,
        id=st.uuids().map(str),
        name=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
            min_size=1,
            max_size=15,
        ),
        oidc_auth=st.just([]),
        contexts=st.lists(
            st.sampled_from(context_pool), min_size=1, max_size=5, unique=True
        ),
    )


def tenant_strategy(context_pool: List[str]) -> st.SearchStrategy:
    """Generate a Tenant with projects whose contexts come from the pool."""
    return st.builds(
        Tenant,
        name=st.text(
            alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
            min_size=1,
            max_size=15,
        ),
        id=st.uuids().map(str),
        projects=st.lists(
            ica_project_strategy(context_pool), min_size=1, max_size=5
        ),
    )


# Composite strategy that generates tenants and deployment contexts from the same pool
@st.composite
def tenants_and_deployment_contexts(draw):
    """Generate a list of tenants and a deployment context list from a shared pool."""
    context_pool = draw(context_pools)
    tenants = draw(
        st.lists(tenant_strategy(context_pool), min_size=1, max_size=4)
    )
    deployment_contexts = draw(
        st.lists(
            st.sampled_from(context_pool), min_size=1, max_size=5, unique=True
        )
    )
    return tenants, deployment_contexts


# --- Property 9: Context-based project filtering ---
# Feature: nf-ica-cli, Property 9: For any ICA configuration (set of tenants/projects
# with context lists) and any deployment context list, the project filter SHALL return
# exactly those projects whose context lists share at least one element with the
# deployment context list.


class TestContextBasedProjectFiltering:
    """**Validates: Requirements 5.2**"""

    @given(data=tenants_and_deployment_contexts())
    @settings(max_examples=100)
    def test_filter_returns_exactly_matching_projects(
        self, data: Tuple[List[Tenant], List[str]]
    ) -> None:
        """Filter returns exactly those projects with at least one shared context.

        For any set of tenants/projects and any deployment context list, the
        filter SHALL include a project if and only if its context list intersects
        with the deployment contexts.
        """
        # Feature: nf-ica-cli, Property 9: Context-based project filtering
        tenants, deployment_contexts = data

        # Call the filter function
        result = filter_projects_by_context(tenants, deployment_contexts)

        # Compute expected result independently
        deployment_set = set(deployment_contexts)
        expected: List[Tuple[Tenant, IcaProject]] = []
        for tenant in tenants:
            for project in tenant.projects:
                if set(project.contexts) & deployment_set:
                    expected.append((tenant, project))

        # Verify exact match: same elements in same order
        assert result == expected

    @given(data=tenants_and_deployment_contexts())
    @settings(max_examples=100)
    def test_all_returned_projects_share_context(
        self, data: Tuple[List[Tenant], List[str]]
    ) -> None:
        """Every returned project shares at least one context with deployment contexts.

        This verifies there are no false positives in the filter output.
        """
        # Feature: nf-ica-cli, Property 9: Context-based project filtering
        tenants, deployment_contexts = data

        result = filter_projects_by_context(tenants, deployment_contexts)

        deployment_set = set(deployment_contexts)
        for _tenant, project in result:
            assert set(project.contexts) & deployment_set, (
                f"Project '{project.name}' with contexts {project.contexts} "
                f"should not be in result for deployment contexts {deployment_contexts}"
            )

    @given(data=tenants_and_deployment_contexts())
    @settings(max_examples=100)
    def test_no_matching_projects_excluded(
        self, data: Tuple[List[Tenant], List[str]]
    ) -> None:
        """No project with matching contexts is excluded from the result.

        This verifies there are no false negatives in the filter output.
        """
        # Feature: nf-ica-cli, Property 9: Context-based project filtering
        tenants, deployment_contexts = data

        result = filter_projects_by_context(tenants, deployment_contexts)

        deployment_set = set(deployment_contexts)
        returned_projects = {(t.id, p.id) for t, p in result}

        for tenant in tenants:
            for project in tenant.projects:
                if set(project.contexts) & deployment_set:
                    assert (tenant.id, project.id) in returned_projects, (
                        f"Project '{project.name}' with contexts {project.contexts} "
                        f"matches deployment contexts {deployment_contexts} but was excluded"
                    )

    @given(
        tenants=st.lists(
            st.builds(
                Tenant,
                name=st.text(
                    alphabet="abcdefghijklmnopqrstuvwxyz",
                    min_size=1,
                    max_size=10,
                ),
                id=st.uuids().map(str),
                projects=st.lists(
                    st.builds(
                        IcaProject,
                        id=st.uuids().map(str),
                        name=st.text(
                            alphabet="abcdefghijklmnopqrstuvwxyz",
                            min_size=1,
                            max_size=10,
                        ),
                        oidc_auth=st.just([]),
                        contexts=st.lists(
                            st.text(
                                alphabet="abcdefghijklmnopqrstuvwxyz",
                                min_size=1,
                                max_size=10,
                            ),
                            min_size=1,
                            max_size=3,
                            unique=True,
                        ),
                    ),
                    min_size=0,
                    max_size=3,
                ),
            ),
            min_size=0,
            max_size=3,
        ),
    )
    @settings(max_examples=100)
    def test_empty_deployment_contexts_returns_empty(
        self, tenants: List[Tenant]
    ) -> None:
        """Empty deployment context list produces empty result.

        When deployment_contexts is empty, no project can share a context,
        so the result SHALL be empty.
        """
        # Feature: nf-ica-cli, Property 9: Context-based project filtering
        result = filter_projects_by_context(tenants, [])
        assert result == []

    @settings(max_examples=100)
    @given(deployment_contexts=st.lists(context_names, min_size=1, max_size=5, unique=True))
    def test_empty_tenants_returns_empty(
        self, deployment_contexts: List[str]
    ) -> None:
        """Empty tenants list produces empty result regardless of deployment contexts.

        When there are no tenants (no projects), the filter SHALL return empty.
        """
        # Feature: nf-ica-cli, Property 9: Context-based project filtering
        result = filter_projects_by_context([], deployment_contexts)
        assert result == []
