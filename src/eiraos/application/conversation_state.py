"""Map the F5-01 conversation aggregate to durable ORM state."""

from eiraos.domains.conversations.models import Conversation
from eiraos.domains.conversations.state import ConversationAggregate, ConversationLifecycle


def hydrate_conversation(row: Conversation) -> ConversationAggregate:
    return ConversationAggregate(
        id=row.id,
        organization_id=row.organization_id,
        owner_user_id=row.user_id,
        title=row.title,
        lifecycle=ConversationLifecycle(row.lifecycle),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        archived_at=row.archived_at,
    )


def new_conversation(aggregate: ConversationAggregate) -> Conversation:
    if aggregate.id is not None:
        raise ValueError("new conversation aggregate already has an identity")
    return Conversation(
        user_id=aggregate.owner_user_id,
        organization_id=aggregate.organization_id,
        title=aggregate.title,
        lifecycle=aggregate.lifecycle.value,
        version=aggregate.version,
        created_at=aggregate.created_at,
        updated_at=aggregate.updated_at,
        archived_at=aggregate.archived_at,
    )


def apply_conversation(row: Conversation, aggregate: ConversationAggregate) -> None:
    if row.id != aggregate.id:
        raise ValueError("conversation identity mismatch")
    if row.organization_id != aggregate.organization_id or row.user_id != aggregate.owner_user_id:
        raise ValueError("conversation scope mismatch")
    row.title = aggregate.title
    row.lifecycle = aggregate.lifecycle.value
    row.version = aggregate.version
    row.updated_at = aggregate.updated_at
    row.archived_at = aggregate.archived_at
