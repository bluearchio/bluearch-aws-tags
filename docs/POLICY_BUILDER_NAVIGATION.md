# Policy Builder - Back Navigation Feature

## Overview

The interactive policy builder now includes comprehensive back navigation, allowing users to return to previous steps and modify their choices without restarting the entire wizard.

## Navigation Features

### Main Menu Navigation

The main menu now includes option **[6]** to edit policy metadata (name and description) at any time:

```
[1] Add new tag rule
[2] Edit existing tag rule
[3] Remove tag rule
[4] Preview policy JSON
[5] Validate policy
[6] Edit policy metadata (name and description)  <- NEW
[7] Save and create policy
[Q] Quit without saving
```

### Adding Tag Rules

When adding a new tag rule, users can go back at multiple decision points:

1. **Tag Name Input**: Type `back` or `b` to return to main menu
2. **Tag Key Input**: Type `back` or `b` to cancel the rule creation
3. **Tag Values Menu**: Select `[B] Go back` to cancel
4. **Inheritance Operator Menu**: Select `[B] Go back` to cancel
5. **Resource Type Selection**: Select `[B] Go back` to cancel

### Resource Type Selection

All resource type selection methods support back navigation:

#### Common Types Selection
- Type `back` or `b` when entering selection to return

#### Service-Based Selection
- Select `[B] Go back` from service list
- Type `back` or `b` when selecting resource types

#### Custom Types Entry
- Type `back` or `b` to return without entering types

### Editing Tag Rules

When editing existing tag rules:
- Select `[B] Go back` from the tag list to return to main menu
- Use `[No]` when asked to replace to cancel the edit

### Removing Tag Rules

When removing tag rules:
- Select `[B] Go back` from the tag list to return to main menu
- Use `[No]` when asked to confirm removal to cancel

## Implementation Details

### Type Annotations
All methods that support back navigation now return `Optional[T]`:
- `_select_resource_types()` returns `Optional[List[str]]`
- `_select_from_common_types()` returns `Optional[List[str]]`
- `_select_by_service()` returns `Optional[List[str]]`
- `_enter_custom_types()` returns `Optional[List[str]]`

### Navigation Handling
Methods check for back navigation keywords and return `None` to signal the caller:
```python
if user_input.lower() in ['back', 'b']:
    console.print("[yellow]Returning to main menu[/yellow]")
    return None
```

Callers check for `None` returns and handle them appropriately:
```python
enforced_resources = self._select_resource_types()
if enforced_resources is None:
    console.print("[yellow]Tag rule cancelled[/yellow]")
    return
```

### State Preservation

The policy builder preserves state across navigation:
- Policy metadata (name and description) are preserved and can be re-edited
- Existing tag rules remain intact when operations are cancelled
- Users can safely explore options and go back without losing work

## User Experience

### Consistent Navigation
- All menu-based selections include `[B] Go back` option
- Text inputs accept `back` or `b` to cancel
- Clear feedback messages when navigating back

### Safety Features
- No data is lost when backing out of operations
- Existing configurations remain unchanged when edits are cancelled
- Confirmation prompts prevent accidental actions

## Examples

### Example 1: Backing Out of Tag Rule Creation

```
[1] Add new tag rule

Tag name/identifier: Environment
Standardized tag key: Environment

Tag values:
[1] Enter allowed values (list)
[2] Enter regex pattern
[3] Any value allowed
[B] Go back

Choice: b
[Tag rule cancelled]
```

### Example 2: Changing Mind on Resource Types

```
Select resource types to enforce:
[1] Choose from common types
[2] Choose by service
[3] Enter custom types
[4] Use wildcard (all supported)
[B] Go back

Choice: 2

Available services:
[1] EC2
[2] S3
...
[B] Go back

Select service: b
[Tag rule cancelled]
```

### Example 3: Re-editing Metadata

User can return to main menu and select option [6] to change policy name and description at any time during the wizard.

## Best Practices

1. **Use Back Navigation Freely**: Don't worry about losing work - the builder preserves your state
2. **Explore Options**: Try different configuration options and back out if needed
3. **Incremental Building**: Add rules one at a time, preview, and adjust as needed
4. **Validate Often**: Use option [5] to validate your policy at any stage

## Technical Notes

- Back navigation is implemented throughout the wizard flow
- All navigation paths properly clean up state
- No memory leaks or stale data from cancelled operations
- Type-safe implementation with proper Optional handling
