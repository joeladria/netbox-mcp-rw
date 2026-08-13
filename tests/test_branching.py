import asyncio
import json
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


class FakeContext:
    """Stand-in for mcp.server.fastmcp.Context; tests set .elicit_result directly."""

    def __init__(self, elicit_result=None):
        self.elicit_result = elicit_result
        self.elicit_calls = []

    async def elicit(self, message, schema):
        self.elicit_calls.append((message, schema))
        return self.elicit_result


class FakeAcceptedElicitation:
    action = "accept"

    def __init__(self, confirm):
        self.data = types.SimpleNamespace(confirm=confirm)


class FakeDeclinedElicitation:
    action = "decline"


class FakeCancelledElicitation:
    action = "cancel"


elicitation_module = types.ModuleType("mcp.server.elicitation")
elicitation_module.AcceptedElicitation = FakeAcceptedElicitation
elicitation_module.DeclinedElicitation = FakeDeclinedElicitation
elicitation_module.CancelledElicitation = FakeCancelledElicitation

fastmcp_module = types.ModuleType("mcp.server.fastmcp")
fastmcp_module.FastMCP = FakeFastMCP
fastmcp_module.Context = FakeContext
server_module = types.ModuleType("mcp.server")
server_module.fastmcp = fastmcp_module
server_module.elicitation = elicitation_module
mcp_module = types.ModuleType("mcp")
mcp_module.server = server_module
sys.modules.setdefault("mcp", mcp_module)
sys.modules.setdefault("mcp.server", server_module)
sys.modules.setdefault("mcp.server.fastmcp", fastmcp_module)
sys.modules.setdefault("mcp.server.elicitation", elicitation_module)

import server
from netbox_client import NetBoxAPIError, NetBoxRestClient


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

    def test_component_template_write_uses_branch_header(self):
        # Component templates (e.g. InterfaceTemplate) are branchable DCIM
        # models, not global/exempt models, so they should behave like any
        # other branchable object type.
        server.netbox.create.return_value = {"id": 1}

        result = server.netbox_create_object(
            "interface-templates",
            {"device_type": 1, "name": "eth0", "type": "1000base-t"},
            branch_schema_id="a1b2c3d4",
        )

        self.assertEqual(result, {"id": 1})
        server.netbox.create.assert_called_once_with(
            "dcim/interface-templates",
            {"device_type": 1, "name": "eth0", "type": "1000base-t"},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
        )

    def test_component_template_read_can_use_branch_context(self):
        server.netbox.get.return_value = []

        server.netbox_get_objects(
            "interface-templates", {"device_type_id": 5}, branch_schema_id="a1b2c3d4"
        )

        server.netbox.get.assert_called_once_with(
            "dcim/interface-templates",
            params={"device_type_id": 5},
            headers={"X-NetBox-Branch": "a1b2c3d4"},
        )

    def test_merge_dry_run_does_not_require_confirmation(self):
        server.netbox.create.return_value = {"id": 10}
        ctx = FakeContext()

        asyncio.run(server.netbox_merge_branch(ctx, 7))

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/merge",
            {"commit": False},
        )
        self.assertEqual(ctx.elicit_calls, [])

    def test_merge_commit_requires_confirmation_and_proceeds_when_confirmed(self):
        server.netbox.create.return_value = {"id": 10}
        ctx = FakeContext(elicit_result=FakeAcceptedElicitation(confirm=True))

        asyncio.run(server.netbox_merge_branch(ctx, 7, commit=True))

        self.assertEqual(len(ctx.elicit_calls), 1)
        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/merge",
            {"commit": True},
        )

    def test_merge_commit_blocked_when_user_declines(self):
        ctx = FakeContext(elicit_result=FakeDeclinedElicitation())

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "declined"):
            asyncio.run(server.netbox_merge_branch(ctx, 7, commit=True))

        server.netbox.create.assert_not_called()

    def test_merge_commit_blocked_when_user_cancels(self):
        ctx = FakeContext(elicit_result=FakeCancelledElicitation())

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "cancelled"):
            asyncio.run(server.netbox_merge_branch(ctx, 7, commit=True))

        server.netbox.create.assert_not_called()

    def test_merge_commit_blocked_when_confirm_false(self):
        ctx = FakeContext(elicit_result=FakeAcceptedElicitation(confirm=False))

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "did not confirm"):
            asyncio.run(server.netbox_merge_branch(ctx, 7, commit=True))

        server.netbox.create.assert_not_called()

    def test_revert_dry_run_does_not_require_confirmation(self):
        server.netbox.create.return_value = {"id": 12}
        ctx = FakeContext()

        asyncio.run(server.netbox_revert_branch(ctx, 7))

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/revert",
            {"commit": False},
        )
        self.assertEqual(ctx.elicit_calls, [])

    def test_revert_commit_requires_confirmation(self):
        ctx = FakeContext(elicit_result=FakeDeclinedElicitation())

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "declined"):
            asyncio.run(server.netbox_revert_branch(ctx, 7, commit=True))

        server.netbox.create.assert_not_called()

    def test_archive_requires_confirmation(self):
        server.netbox.create.return_value = {"id": 13}
        ctx = FakeContext(elicit_result=FakeAcceptedElicitation(confirm=True))

        asyncio.run(server.netbox_archive_branch(ctx, 7))

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/archive",
            {},
        )

    def test_archive_blocked_without_confirmation(self):
        ctx = FakeContext(elicit_result=FakeDeclinedElicitation())

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "declined"):
            asyncio.run(server.netbox_archive_branch(ctx, 7))

        server.netbox.create.assert_not_called()

    def test_delete_branch_requires_confirmation(self):
        server.netbox.delete.return_value = True
        ctx = FakeContext(elicit_result=FakeAcceptedElicitation(confirm=True))

        result = asyncio.run(server.netbox_delete_branch(ctx, 7))

        self.assertEqual(result, {"success": True, "message": "Deleted branch 7"})
        server.netbox.delete.assert_called_once_with("plugins/branching/branches", 7)

    def test_delete_branch_blocked_without_confirmation(self):
        ctx = FakeContext(elicit_result=FakeDeclinedElicitation())

        with self.assertRaisesRegex(server.ConfirmationRequiredError, "declined"):
            asyncio.run(server.netbox_delete_branch(ctx, 7))

        server.netbox.delete.assert_not_called()

    def test_sync_can_acknowledge_conflicts(self):
        server.netbox.create.return_value = {"id": 11}

        server.netbox_sync_branch(7, commit=True, acknowledge_conflicts=True)

        server.netbox.create.assert_called_once_with(
            "plugins/branching/branches/7/sync",
            {"commit": True, "acknowledge_conflicts": True},
        )


class CustomFieldDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.old_netbox = server.netbox
        server.netbox = MagicMock()
        server._content_type_cache.clear()

    def tearDown(self):
        server.netbox = self.old_netbox
        server._content_type_cache.clear()

    def test_resolve_content_type_matches_object_type_endpoint(self):
        server.netbox.get.return_value = [
            {
                "app_label": "dcim",
                "model": "site",
                "rest_api_endpoint": "/api/dcim/sites/",
            },
            {
                "app_label": "dcim",
                "model": "device",
                "rest_api_endpoint": "/api/dcim/devices/",
            },
        ]

        result = server._resolve_content_type("devices")

        self.assertEqual(result, "dcim.device")
        server.netbox.get.assert_called_once_with(
            "core/object-types", params={"app_label": "dcim"}
        )

    def test_resolve_content_type_caches_result(self):
        server.netbox.get.return_value = [
            {
                "app_label": "dcim",
                "model": "device",
                "rest_api_endpoint": "/api/dcim/devices/",
            },
        ]

        first = server._resolve_content_type("devices")
        second = server._resolve_content_type("devices")

        self.assertEqual(first, "dcim.device")
        self.assertEqual(second, "dcim.device")
        server.netbox.get.assert_called_once()

    def test_resolve_content_type_raises_when_no_match(self):
        server.netbox.get.return_value = [
            {
                "app_label": "dcim",
                "model": "site",
                "rest_api_endpoint": "/api/dcim/sites/",
            },
        ]

        with self.assertRaisesRegex(ValueError, "Could not resolve NetBox content type"):
            server._resolve_content_type("devices")

    def test_resolve_content_type_rejects_invalid_object_type(self):
        with self.assertRaisesRegex(ValueError, "Invalid object_type"):
            server._resolve_content_type("not-a-real-type")
        server.netbox.get.assert_not_called()

    def test_get_custom_fields_filters_by_resolved_content_type(self):
        server.netbox.get.side_effect = [
            [
                {
                    "app_label": "dcim",
                    "model": "device",
                    "rest_api_endpoint": "/api/dcim/devices/",
                }
            ],
            [{"id": 1, "name": "site_code", "type": {"value": "text"}}],
        ]

        result = server.netbox_get_custom_fields("devices")

        self.assertEqual(result, [{"id": 1, "name": "site_code", "type": {"value": "text"}}])
        server.netbox.get.assert_any_call(
            "core/object-types", params={"app_label": "dcim"}
        )
        server.netbox.get.assert_any_call(
            "extras/custom-fields", params={"object_type": "dcim.device"}
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


class NetBoxAPIErrorTest(unittest.TestCase):
    """Verify 4xx/5xx responses raise NetBoxAPIError with response body details."""

    @staticmethod
    def _make_response(status_code, reason, url, json_body=None, text_body=None):
        import requests

        response = requests.Response()
        response.status_code = status_code
        response.reason = reason
        response.url = url
        if json_body is not None:
            response._content = json.dumps(json_body).encode("utf-8")
        elif text_body is not None:
            response._content = text_body.encode("utf-8")
        return response

    def setUp(self):
        self.client = NetBoxRestClient("https://netbox.example.com", "token")

    def test_update_raises_netbox_api_error_with_field_details(self):
        response = self._make_response(
            400,
            "Bad Request",
            "https://netbox.example.com/api/dcim/devices/6087/",
            json_body={"primary_ip4": ['Invalid pk "3934" - object does not exist.']},
        )
        self.client.session.patch = MagicMock(return_value=response)

        with self.assertRaises(NetBoxAPIError) as ctx:
            self.client.update("dcim/devices", 6087, {"primary_ip4": 3934})

        err = ctx.exception
        self.assertEqual(err.status_code, 400)
        self.assertEqual(
            err.error_details, {"primary_ip4": ['Invalid pk "3934" - object does not exist.']}
        )
        self.assertIn("primary_ip4", str(err))
        self.assertIn("does not exist", str(err))

    def test_create_raises_netbox_api_error_with_list_details(self):
        response = self._make_response(
            400,
            "Bad Request",
            "https://netbox.example.com/api/dcim/modules/",
            json_body=["Module type is not compatible with this bay."],
        )
        self.client.session.post = MagicMock(return_value=response)

        with self.assertRaises(NetBoxAPIError) as ctx:
            self.client.create("dcim/modules", {"device": 6087, "module_type": 427, "module_bay": 1})

        self.assertIn("Module type is not compatible", str(ctx.exception))

    def test_error_falls_back_to_raw_text_when_not_json(self):
        response = self._make_response(
            500,
            "Internal Server Error",
            "https://netbox.example.com/api/dcim/devices/6087/",
            text_body="<html>Server Error</html>",
        )
        self.client.session.patch = MagicMock(return_value=response)

        with self.assertRaises(NetBoxAPIError) as ctx:
            self.client.update("dcim/devices", 6087, {"status": "active"})

        self.assertIn("Server Error", str(ctx.exception))

    def test_successful_response_does_not_raise(self):
        response = self._make_response(
            200,
            "OK",
            "https://netbox.example.com/api/dcim/devices/6087/",
            json_body={"id": 6087, "status": "active"},
        )
        self.client.session.patch = MagicMock(return_value=response)

        result = self.client.update("dcim/devices", 6087, {"status": "active"})

        self.assertEqual(result, {"id": 6087, "status": "active"})


if __name__ == "__main__":
    unittest.main()
