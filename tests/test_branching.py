import os
import sys
import types
import unittest
from unittest.mock import MagicMock


class FakeFastMCP:
    def __init__(self, *args, **kwargs):
        pass

    def tool(self):
        return lambda func: func

    def run(self, *args, **kwargs):
        pass


fastmcp_module = types.ModuleType("mcp.server.fastmcp")
fastmcp_module.FastMCP = FakeFastMCP
server_module = types.ModuleType("mcp.server")
server_module.fastmcp = fastmcp_module
mcp_module = types.ModuleType("mcp")
mcp_module.server = server_module
sys.modules.setdefault("mcp", mcp_module)
sys.modules.setdefault("mcp.server", server_module)
sys.modules.setdefault("mcp.server.fastmcp", fastmcp_module)

import server
from netbox_client import NetBoxRestClient


class BranchWriteGuardTest(unittest.TestCase):
    def setUp(self):
        self.old_netbox = server.netbox
        server.netbox = MagicMock()
        os.environ.pop("NETBOX_ALLOW_MAIN_COMMIT", None)

    def tearDown(self):
        server.netbox = self.old_netbox
        os.environ.pop("NETBOX_ALLOW_MAIN_COMMIT", None)

    def test_branchable_write_requires_branch_by_default(self):
        with self.assertRaisesRegex(ValueError, "require branch_schema_id"):
            server.netbox_create_object("sites", {"name": "Site A"})
        server.netbox.create.assert_not_called()

    def test_branchable_write_uses_branch_header(self):
        server.netbox.create.return_value = {"id": 1}

        result = server.netbox_create_object("sites", {"name": "Site A"}, branch_schema_id="a1b2c3d4")

        self.assertEqual(result, {"id": 1})
        server.netbox.create.assert_called_once_with(
            "dcim/sites",
            {"name": "Site A"},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
        )

    def test_main_commit_env_allows_branchable_write_without_branch(self):
        os.environ["NETBOX_ALLOW_MAIN_COMMIT"] = "true"
        server.netbox.update.return_value = {"id": 1}

        server.netbox_update_object("sites", 1, {"status": "active"})

        server.netbox.update.assert_called_once_with(
            "dcim/sites",
            1,
            {"status": "active"},
            headers=None,
        )

    def test_global_write_is_blocked_by_default(self):
        with self.assertRaisesRegex(ValueError, "global/non-branchable"):
            server.netbox_create_object("custom-fields", {"name": "cf_site_code"})
        server.netbox.create.assert_not_called()

    def test_global_write_rejects_branch_header_even_when_main_allowed(self):
        os.environ["NETBOX_ALLOW_MAIN_COMMIT"] = "true"

        with self.assertRaisesRegex(ValueError, "not branch-isolated"):
            server.netbox_create_object(
                "custom-fields",
                {"name": "cf_site_code"},
                branch_schema_id="a1b2c3d4",
            )
        server.netbox.create.assert_not_called()

    def test_global_write_allowed_when_main_commit_enabled(self):
        os.environ["NETBOX_ALLOW_MAIN_COMMIT"] = "true"
        server.netbox.create.return_value = {"id": 1}

        server.netbox_create_object("custom-fields", {"name": "cf_site_code"})

        server.netbox.create.assert_called_once_with(
            "extras/custom-fields",
            {"name": "cf_site_code"},
            headers=None,
        )

    def test_read_can_use_branch_context(self):
        server.netbox.get.return_value = []

        server.netbox_get_objects("devices", {"name": "leaf1"}, branch_schema_id="a1b2c3d4")

        server.netbox.get.assert_called_once_with(
            "dcim/devices",
            params={"name": "leaf1"},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
        )

    def test_merge_defaults_to_dry_run(self):
        server.netbox.create.return_value = {"id": 10}

        server.netbox_merge_branch(7)

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/merge",
            {"commit": False},
        )

    def test_sync_can_acknowledge_conflicts(self):
        server.netbox.create.return_value = {"id": 11}

        server.netbox_sync_branch(7, commit=True, acknowledge_conflicts=True)

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/sync",
            {"commit": True, "acknowledge_conflicts": True},
        )


class NetBoxRestClientHeadersTest(unittest.TestCase):
    def test_create_passes_per_request_headers(self):
        client = NetBoxRestClient("https://netbox.example.com", "token")
        response = MagicMock()
        response.json.return_value = {"id": 1}
        client.session.post = MagicMock(return_value=response)

        result = client.create("dcim/sites", {"name": "Site A"}, headers={"X-NetBox-Branch": "a1b2c3d4"})

        self.assertEqual(result, {"id": 1})
        client.session.post.assert_called_once_with(
            "https://netbox.example.com/api/dcim/sites/",
            json={"name": "Site A"},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
            verify=True,
        )
        response.raise_for_status.assert_called_once()

    def test_get_passes_per_request_headers(self):
        client = NetBoxRestClient("https://netbox.example.com", "token")
        response = MagicMock()
        response.json.return_value = {"results": [{"id": 1}]}
        client.session.get = MagicMock(return_value=response)

        result = client.get("dcim/sites", params={"name": "Site A"}, headers={"X-NetBox-Branch": "a1b2c3d4"})

        self.assertEqual(result, [{"id": 1}])
        client.session.get.assert_called_once_with(
            "https://netbox.example.com/api/dcim/sites/",
            params={"name": "Site A"},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
            verify=True,
        )
        response.raise_for_status.assert_called_once()


if __name__ == "__main__":
    unittest.main()
