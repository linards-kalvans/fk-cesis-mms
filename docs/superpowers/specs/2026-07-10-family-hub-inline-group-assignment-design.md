# Family hub inline group assignment — design

Date: 2026-07-10
Status: approved for implementation

## Problem

The Family hub shows active members without a training group as `Bez grupas` with next action `Piešķirt grupu`, but staff cannot assign the group directly from that lane.

## Scope

In scope:
- Add an inline training-group dropdown and submit button in the Family hub `Dalība` lane for active members with no group.
- Use existing active training groups from hub context.
- Reuse existing `assign_training_group(member, group, actor)` service.
- Add a Family hub POST action that verifies the member belongs to the Guardian.

Out of scope:
- Group reassignment for already-assigned members from this inline form.
- Inactive group selection.
- New models, migrations, or JavaScript.

## Design

Render a small inline form under `Dalība` when `child.member` exists and `child.member.training_group_id` is empty. The form posts to the existing Family hub action URL with `action=assign_training_group`, `member_id`, and `training_group`.

Add `_family_hub_handle_assign_training_group` to `GuardianAdmin`. It loads the member through `_get_guardian_member`, resolves the selected group through `_resolve_training_group`, requires a selected active group, calls `assign_training_group`, shows an admin message, and redirects back through the existing action view flow.

## Acceptance criteria

- An active member with no group shows a dropdown of active groups and a `Piešķirt grupu` button in `Dalība`.
- Submitting the form assigns the selected group.
- A member that already has a group does not show the inline assignment form.
- Cross-family member ids return 404.
- No migration is generated.
