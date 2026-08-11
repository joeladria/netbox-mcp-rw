from mcp.server.elicitation import AcceptedElicitation, CancelledElicitation, DeclinedElicitation
from mcp.server.fastmcp import Context, FastMCP
from netbox_client import NetBoxRestClient
from pydantic import BaseModel
import os

# Mapping of simple object names to API endpoints
NETBOX_OBJECT_TYPES = {
    # DCIM (Device and Infrastructure)
    "cables": "dcim/cables",
    "cable-bundles": "dcim/cable-bundles",
    "console-ports": "dcim/console-ports", 
    "console-server-ports": "dcim/console-server-ports",
    "devices": "dcim/devices",
    "device-bays": "dcim/device-bays",
    "device-roles": "dcim/device-roles",
    "device-types": "dcim/device-types",
    "front-ports": "dcim/front-ports",
    "interfaces": "dcim/interfaces",
    "inventory-items": "dcim/inventory-items",
    "locations": "dcim/locations",
    "mac-addresses": "dcim/mac-addresses",
    "manufacturers": "dcim/manufacturers",
    "modules": "dcim/modules",
    "module-bays": "dcim/module-bays",
    "module-types": "dcim/module-types",
    "platforms": "dcim/platforms",
    "power-feeds": "dcim/power-feeds",
    "power-outlets": "dcim/power-outlets",
    "power-panels": "dcim/power-panels",
    "power-ports": "dcim/power-ports",
    "racks": "dcim/racks",
    "rack-groups": "dcim/rack-groups",
    "rack-reservations": "dcim/rack-reservations",
    "rack-roles": "dcim/rack-roles",
    "regions": "dcim/regions",
    "sites": "dcim/sites",
    "site-groups": "dcim/site-groups",
    "virtual-chassis": "dcim/virtual-chassis",
    "virtual-device-contexts": "dcim/virtual-device-contexts",
    
    # IPAM (IP Address Management)
    "asns": "ipam/asns",
    "asn-ranges": "ipam/asn-ranges", 
    "aggregates": "ipam/aggregates",
    "fhrp-groups": "ipam/fhrp-groups",
    "ip-addresses": "ipam/ip-addresses",
    "ip-ranges": "ipam/ip-ranges",
    "prefixes": "ipam/prefixes",
    "rirs": "ipam/rirs",
    "roles": "ipam/roles",
    "route-targets": "ipam/route-targets",
    "services": "ipam/services",
    "vlans": "ipam/vlans",
    "vlan-groups": "ipam/vlan-groups",
    "vrfs": "ipam/vrfs",
    
    # Circuits
    "circuits": "circuits/circuits",
    "circuit-groups": "circuits/circuit-groups",
    "circuit-types": "circuits/circuit-types",
    "circuit-terminations": "circuits/circuit-terminations",
    "providers": "circuits/providers",
    "provider-accounts": "circuits/provider-accounts",
    "provider-networks": "circuits/provider-networks",
    "virtual-circuits": "circuits/virtual-circuits",
    
    # Virtualization
    "clusters": "virtualization/clusters",
    "cluster-groups": "virtualization/cluster-groups",
    "cluster-types": "virtualization/cluster-types",
    "virtual-disks": "virtualization/virtual-disks",
    "virtual-machines": "virtualization/virtual-machines",
    "virtual-machine-types": "virtualization/virtual-machine-types",
    "vm-interfaces": "virtualization/interfaces",
    
    # Tenancy
    "tenants": "tenancy/tenants",
    "tenant-groups": "tenancy/tenant-groups",
    "contacts": "tenancy/contacts",
    "contact-groups": "tenancy/contact-groups",
    "contact-roles": "tenancy/contact-roles",
    "contact-assignments": "tenancy/contact-assignments",
    
    # VPN
    "ike-policies": "vpn/ike-policies",
    "ike-proposals": "vpn/ike-proposals",
    "ipsec-policies": "vpn/ipsec-policies",
    "ipsec-profiles": "vpn/ipsec-profiles",
    "ipsec-proposals": "vpn/ipsec-proposals",
    "l2vpns": "vpn/l2vpns",
    "l2vpn-terminations": "vpn/l2vpn-terminations",
    "tunnels": "vpn/tunnels",
    "tunnel-groups": "vpn/tunnel-groups",
    "tunnel-terminations": "vpn/tunnel-terminations",
    
    # Wireless
    "wireless-lans": "wireless/wireless-lans",
    "wireless-lan-groups": "wireless/wireless-lan-groups",
    "wireless-links": "wireless/wireless-links",

    # Extras
    "config-contexts": "extras/config-contexts",
    "config-context-profiles": "extras/config-context-profiles",
    "custom-fields": "extras/custom-fields",
    "custom-field-choice-sets": "extras/custom-field-choice-sets",
    "event-rules": "extras/event-rules",
    "export-templates": "extras/export-templates",
    "image-attachments": "extras/image-attachments",
    "jobs": "core/jobs",
    "saved-filters": "extras/saved-filters",
    "scripts": "extras/scripts",
    "tags": "extras/tags",
    "webhooks": "extras/webhooks",
}

mcp = FastMCP("NetBox", log_level="DEBUG")
netbox = None

GLOBAL_OBJECT_TYPES = {
    "config-contexts",
    "config-context-profiles",
    "custom-fields",
    "custom-field-choice-sets",
    "event-rules",
    "export-templates",
    "jobs",
    "saved-filters",
    "scripts",
    "tags",
    "webhooks",
}


def _allow_main_commit() -> bool:
    return os.getenv("NETBOX_ALLOW_MAIN_COMMIT", "").lower() in {"1", "true", "yes", "on"}


class ConfirmAction(BaseModel):
    """Schema used to elicit explicit user confirmation for a destructive branch action."""

    confirm: bool


class ConfirmationRequiredError(RuntimeError):
    """Raised when a destructive branch action is not confirmed by the user."""


async def _require_confirmation(ctx: Context, message: str) -> None:
    """
    Mandatorily prompt the connected client/user for confirmation via MCP elicitation
    before proceeding with a destructive/irreversible branch operation.

    Raises ConfirmationRequiredError unless the user explicitly accepts with confirm=True.
    """
    if ctx is None:
        raise ConfirmationRequiredError(
            "Confirmation is required for this action but no request context is available."
        )

    result = await ctx.elicit(message=message, schema=ConfirmAction)

    if isinstance(result, AcceptedElicitation):
        if not result.data.confirm:
            raise ConfirmationRequiredError("User did not confirm this action (confirm=false). Aborting.")
        return
    if isinstance(result, DeclinedElicitation):
        raise ConfirmationRequiredError("User declined to confirm this action. Aborting.")
    if isinstance(result, CancelledElicitation):
        raise ConfirmationRequiredError("User cancelled the confirmation prompt. Aborting.")

    raise ConfirmationRequiredError("Unexpected confirmation result. Aborting.")


def _validate_object_type(object_type: str) -> str:
    if object_type not in NETBOX_OBJECT_TYPES:
        valid_types = "\n".join(f"- {t}" for t in sorted(NETBOX_OBJECT_TYPES.keys()))
        raise ValueError(f"Invalid object_type. Must be one of:\n{valid_types}")
    return NETBOX_OBJECT_TYPES[object_type]


def _branch_headers(branch_schema_id: str | None) -> dict | None:
    if branch_schema_id:
        return {"X-NetBox-Branch": branch_schema_id}
    return None


def _write_headers(object_type: str, branch_schema_id: str | None) -> dict | None:
    if object_type in GLOBAL_OBJECT_TYPES:
        if branch_schema_id:
            raise ValueError(
                f"{object_type} is not branch-isolated in NetBox Branching. "
                "Omit branch_schema_id and set NETBOX_ALLOW_MAIN_COMMIT=true to write it globally."
            )
        if _allow_main_commit():
            return None
        raise ValueError(
            f"{object_type} is a global/non-branchable NetBox model. "
            "Set NETBOX_ALLOW_MAIN_COMMIT=true to allow this main/global write."
        )

    if branch_schema_id:
        return _branch_headers(branch_schema_id)
    if _allow_main_commit():
        return None
    raise ValueError(
        "Writes to branchable NetBox models require branch_schema_id. "
        "Set NETBOX_ALLOW_MAIN_COMMIT=true only if this write should commit directly to main."
    )

@mcp.tool()
def netbox_get_objects(object_type: str, filters: dict, branch_schema_id: str | None = None):
    """
    Get objects from NetBox based on their type and filters
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        filters: dict of filters to apply to the API call based on the NetBox API filtering options
    
    Valid object_type values:
    
    DCIM (Device and Infrastructure):
    - cables
    - console-ports
    - console-server-ports  
    - devices
    - device-bays
    - device-roles
    - device-types
    - front-ports
    - interfaces
    - inventory-items
    - locations
    - manufacturers
    - modules
    - module-bays
    - module-types
    - platforms
    - power-feeds
    - power-outlets
    - power-panels
    - power-ports
    - racks
    - rack-reservations
    - rack-roles
    - regions
    - sites
    - site-groups
    - virtual-chassis
    
    IPAM (IP Address Management):
    - asns
    - asn-ranges
    - aggregates 
    - fhrp-groups
    - ip-addresses
    - ip-ranges
    - prefixes
    - rirs
    - roles
    - route-targets
    - services
    - vlans
    - vlan-groups
    - vrfs
    
    Circuits:
    - circuits
    - circuit-types
    - circuit-terminations
    - providers
    - provider-networks
    
    Virtualization:
    - clusters
    - cluster-groups
    - cluster-types
    - virtual-machines
    - vm-interfaces
    
    Tenancy:
    - tenants
    - tenant-groups
    - contacts
    - contact-groups
    - contact-roles
    
    VPN:
    - ike-policies
    - ike-proposals
    - ipsec-policies
    - ipsec-profiles
    - ipsec-proposals
    - l2vpns
    - tunnels
    - tunnel-groups
    
    Wireless:
    - wireless-lans
    - wireless-lan-groups
    - wireless-links
    
    See NetBox API documentation for filtering options for each object type.
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    return netbox.get(endpoint, params=filters, headers=_branch_headers(branch_schema_id))

@mcp.tool()
def netbox_get_object_by_id(object_type: str, object_id: int, branch_schema_id: str | None = None):
    """
    Get detailed information about a specific NetBox object by its ID.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        object_id: The numeric ID of the object
    
    Returns:
        Complete object details
    """
    endpoint = _validate_object_type(object_type)
    
    return netbox.get(endpoint, id=object_id, headers=_branch_headers(branch_schema_id))

@mcp.tool()
def netbox_get_changelogs(filters: dict):
    """
    Get object change records (changelogs) from NetBox based on filters.
    
    Args:
        filters: dict of filters to apply to the API call based on the NetBox API filtering options
    
    Returns:
        List of changelog objects matching the specified filters
    
    Filtering options include:
    - user_id: Filter by user ID who made the change
    - user: Filter by username who made the change
    - changed_object_type_id: Filter by ContentType ID of the changed object
    - changed_object_id: Filter by ID of the changed object
    - object_repr: Filter by object representation (usually contains object name)
    - action: Filter by action type (created, updated, deleted)
    - time_before: Filter for changes made before a given time (ISO 8601 format)
    - time_after: Filter for changes made after a given time (ISO 8601 format)
    - q: Search term to filter by object representation

    Example:
    To find all changes made to a specific device with ID 123:
    {"changed_object_type_id": "dcim.device", "changed_object_id": 123}
    
    To find all deletions in the last 24 hours:
    {"action": "delete", "time_after": "2023-01-01T00:00:00Z"}
    
    Each changelog entry contains:
    - id: The unique identifier of the changelog entry
    - user: The user who made the change
    - user_name: The username of the user who made the change
    - request_id: The unique identifier of the request that made the change
    - action: The type of action performed (created, updated, deleted)
    - changed_object_type: The type of object that was changed
    - changed_object_id: The ID of the object that was changed
    - object_repr: String representation of the changed object
    - object_data: The object's data after the change (null for deletions)
    - object_data_v2: Enhanced data representation
    - prechange_data: The object's data before the change (null for creations)
    - postchange_data: The object's data after the change (null for deletions)
    - time: The timestamp when the change was made
    """
    endpoint = "core/object-changes"
    
    # Make API call
    return netbox.get(endpoint, params=filters)

@mcp.tool()
def netbox_create_object(object_type: str, data: dict, branch_schema_id: str | None = None):
    """
    Create a new object in NetBox.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        data: Dict containing the object data to create
        
    Returns:
        The created object as a dict
        
    Example:
    To create a new site:
    netbox_create_object("sites", {
        "name": "New Site",
        "slug": "new-site", 
        "status": "active"
    })
    
    To create a new device:
    netbox_create_object("devices", {
        "name": "new-device",
        "device_type": 1,  # ID of device type
        "site": 1,         # ID of site
        "role": 1,         # ID of device role
        "status": "active"
    })
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    return netbox.create(endpoint, data, headers=_write_headers(object_type, branch_schema_id))

@mcp.tool()
def netbox_update_object(object_type: str, object_id: int, data: dict, branch_schema_id: str | None = None):
    """
    Update an existing object in NetBox.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        object_id: The numeric ID of the object to update
        data: Dict containing the object data to update (only changed fields needed)
        
    Returns:
        The updated object as a dict
        
    Example:
    To update a site's description:
    netbox_update_object("sites", 1, {"description": "Updated description"})
    
    To change a device's status:
    netbox_update_object("devices", 5, {"status": "offline"})
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    return netbox.update(endpoint, object_id, data, headers=_write_headers(object_type, branch_schema_id))

@mcp.tool()
def netbox_delete_object(object_type: str, object_id: int, branch_schema_id: str | None = None):
    """
    Delete an object from NetBox.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        object_id: The numeric ID of the object to delete
        
    Returns:
        True if deletion was successful
        
    WARNING: This permanently deletes the object and cannot be undone!
    
    Example:
    To delete a device:
    netbox_delete_object("devices", 5)
    
    To delete an IP address:
    netbox_delete_object("ip-addresses", 123)
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call - this will raise an exception if it fails
    success = netbox.delete(endpoint, object_id, headers=_write_headers(object_type, branch_schema_id))
    
    if success:
        return {"success": True, "message": f"Successfully deleted {object_type} with ID {object_id}"}
    else:
        return {"success": False, "message": f"Failed to delete {object_type} with ID {object_id}"}

@mcp.tool()
def netbox_bulk_create_objects(object_type: str, data: list, branch_schema_id: str | None = None):
    """
    Create multiple objects in NetBox in a single request.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        data: List of dicts containing the object data to create
        
    Returns:
        List of created objects
        
    Example:
    To create multiple sites:
    netbox_bulk_create_objects("sites", [
        {"name": "Site A", "slug": "site-a", "status": "active"},
        {"name": "Site B", "slug": "site-b", "status": "active"}
    ])
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    return netbox.bulk_create(endpoint, data, headers=_write_headers(object_type, branch_schema_id))

@mcp.tool()
def netbox_bulk_update_objects(object_type: str, data: list, branch_schema_id: str | None = None):
    """
    Update multiple objects in NetBox in a single request.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")
        data: List of dicts containing the object data to update (must include "id" field)
        
    Returns:
        List of updated objects
        
    Example:
    To update multiple devices:
    netbox_bulk_update_objects("devices", [
        {"id": 1, "status": "offline"},
        {"id": 2, "status": "maintenance"}
    ])
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    return netbox.bulk_update(endpoint, data, headers=_write_headers(object_type, branch_schema_id))

@mcp.tool()
def netbox_bulk_delete_objects(object_type: str, object_ids: list, branch_schema_id: str | None = None):
    """
    Delete multiple objects from NetBox in a single request.
    
    Args:
        object_type: String representing the NetBox object type (e.g. "devices", "ip-addresses")  
        object_ids: List of numeric IDs to delete
        
    Returns:
        Success status
        
    WARNING: This permanently deletes the objects and cannot be undone!
    
    Example:
    To delete multiple devices:
    netbox_bulk_delete_objects("devices", [5, 6, 7])
    """
    endpoint = _validate_object_type(object_type)
        
    # Make API call
    success = netbox.bulk_delete(endpoint, object_ids, headers=_write_headers(object_type, branch_schema_id))
    
    if success:
        return {"success": True, "message": f"Successfully deleted {len(object_ids)} {object_type} objects"}
    else:
        return {"success": False, "message": f"Failed to delete {object_type} objects"}


@mcp.tool()
def netbox_list_branches(filters: dict):
    """List NetBox Branching branches."""
    return netbox.get("plugins/branching/branches", params=filters)


@mcp.tool()
def netbox_get_branch(branch_id: int):
    """Get a NetBox Branching branch by numeric ID."""
    return netbox.get("plugins/branching/branches", id=branch_id)


@mcp.tool()
def netbox_create_branch(name: str, description: str = ""):
    """Create a NetBox Branching branch. Use the returned schema_id for branch-scoped reads and writes."""
    data = {"name": name}
    if description:
        data["description"] = description
    return netbox.create("plugins/branching/branches", data)


@mcp.tool()
def netbox_get_branch_changes(branch_id: int, filters: dict):
    """Get ChangeDiff records for a branch."""
    params = dict(filters or {})
    params["branch_id"] = branch_id
    return netbox.get("plugins/branching/changes", params=params)


@mcp.tool()
def netbox_get_branch_events(branch_id: int, filters: dict):
    """Get branch lifecycle events for a branch."""
    params = dict(filters or {})
    params["branch_id"] = branch_id
    return netbox.get("plugins/branching/branch-events", params=params)


@mcp.tool()
def netbox_get_branchable_models():
    """Discover models configured as branchable on this NetBox instance."""
    return netbox.get("plugins/branching/branchable-models")


@mcp.tool()
def netbox_sync_branch(branch_id: int, commit: bool = False, acknowledge_conflicts: bool = False):
    """Sync main into a branch. Defaults to dry-run with commit=false."""
    data = {"commit": commit}
    if acknowledge_conflicts:
        data["acknowledge_conflicts"] = True
    return netbox.create(f"plugins/branching/branches/{branch_id}/sync", data)


@mcp.tool()
async def netbox_merge_branch(
    ctx: Context,
    branch_id: int,
    commit: bool = False,
    acknowledge_conflicts: bool = False,
    strategy: str | None = None,
):
    """Merge a branch to main. Defaults to dry-run with commit=false.

    When commit=true, this mutates main and requires interactive user
    confirmation via MCP elicitation before proceeding.
    """
    if commit:
        await _require_confirmation(
            ctx,
            f"Merge branch {branch_id} into main? This will commit the branch's changes to main "
            "and cannot be undone without a separate revert. Confirm to proceed.",
        )
    data = {"commit": commit}
    if acknowledge_conflicts:
        data["acknowledge_conflicts"] = True
    if strategy:
        data["strategy"] = strategy
    return netbox.create(f"plugins/branching/branches/{branch_id}/merge", data)


@mcp.tool()
async def netbox_revert_branch(ctx: Context, branch_id: int, commit: bool = False):
    """Revert a previously merged branch. Defaults to dry-run with commit=false.

    When commit=true, this mutates main and requires interactive user
    confirmation via MCP elicitation before proceeding.
    """
    if commit:
        await _require_confirmation(
            ctx,
            f"Revert previously merged branch {branch_id}? This will undo its changes on main "
            "and cannot be undone without a separate action. Confirm to proceed.",
        )
    return netbox.create(f"plugins/branching/branches/{branch_id}/revert", {"commit": commit})


@mcp.tool()
async def netbox_archive_branch(ctx: Context, branch_id: int):
    """Archive a ready or merged branch.

    Requires interactive user confirmation via MCP elicitation before proceeding.
    """
    await _require_confirmation(
        ctx,
        f"Archive branch {branch_id}? Archived branches can no longer be modified or merged. "
        "Confirm to proceed.",
    )
    return netbox.create(f"plugins/branching/branches/{branch_id}/archive", {})


@mcp.tool()
async def netbox_delete_branch(ctx: Context, branch_id: int):
    """Delete a branch record and drop its schema.

    WARNING: This permanently deletes the branch and its schema and cannot be
    undone. Requires interactive user confirmation via MCP elicitation before
    proceeding.
    """
    await _require_confirmation(
        ctx,
        f"Permanently delete branch {branch_id} and drop its schema? This cannot be undone. "
        "Confirm to proceed.",
    )
    success = netbox.delete("plugins/branching/branches", branch_id)
    return {"success": success, "message": f"Deleted branch {branch_id}" if success else f"Failed to delete branch {branch_id}"}

if __name__ == "__main__":
    # Load NetBox configuration from environment variables
    netbox_url = os.getenv("NETBOX_URL")
    netbox_token = os.getenv("NETBOX_TOKEN")
    
    if not netbox_url or not netbox_token:
        raise ValueError("NETBOX_URL and NETBOX_TOKEN environment variables must be set")
    
    # Initialize NetBox client
    netbox = NetBoxRestClient(url=netbox_url, token=netbox_token)
    
    mcp.run(transport="stdio")
