import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class AssetzController(http.Controller):
    """Controller for handling QR code scans and public asset views."""

    @http.route(
        "/assetz/asset/<int:asset_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def asset_details_public(self, asset_id, **kwargs):
        """
        Public page to display asset details when QR code is scanned.
        This page shows asset information, current location, and current holder.
        """
        asset = request.env["assetz.asset"].sudo().browse(asset_id)

        if not asset.exists():
            return request.render(
                "assetz.asset_not_found",
                {"error_message": "Asset not found"},
            )

        # Prepare asset data for display
        values = {
            "asset": asset,
            "page_title": f"Asset: {asset.name}",
        }

        return request.render("assetz.asset_details_public", values)

    @http.route(
        "/assetz/asset/scan/<string:code>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def asset_scan_by_code(self, code, **kwargs):
        """
        Alternative route to find asset by code (e.g., AST-00001).
        Useful when QR contains just the asset code.
        """
        asset = request.env["assetz.asset"].sudo().search(
            [("code", "=", code)], limit=1
        )

        if not asset:
            return request.render(
                "assetz.asset_not_found",
                {"error_message": f"Asset with code '{code}' not found"},
            )

        # Redirect to the main asset details page
        return request.redirect(f"/assetz/asset/{asset.id}")

    @http.route(
        "/assetz/asset/json/<int:asset_id>",
        type="json",
        auth="public",
        csrf=False,
    )
    def asset_details_json(self, asset_id, **kwargs):
        """
        JSON endpoint for programmatic access to asset details.
        Useful for mobile apps or API integrations.
        """
        asset = request.env["assetz.asset"].sudo().browse(asset_id)

        if not asset.exists():
            return {"error": "Asset not found", "success": False}

        return {
            "success": True,
            "asset": {
                "id": asset.id,
                "code": asset.code,
                "name": asset.name,
                "serial_number": asset.serial_number or "",
                "category": asset.category_id.name if asset.category_id else "",
                "state": dict(asset._fields["state"].selection).get(asset.state, asset.state),
                "issue_state": dict(asset._fields["issue_state"].selection).get(
                    asset.issue_state, asset.issue_state
                ),
                "location": {
                    "id": asset.location_id.id if asset.location_id else None,
                    "name": asset.location_id.complete_name if asset.location_id else "",
                },
                "current_holder": {
                    "type": asset.current_holder_type or "",
                    "name": asset.current_holder_display or "",
                },
                "acquisition_date": str(asset.acquisition_date) if asset.acquisition_date else "",
                "manufacturer": asset.manufacturer or "",
                "model": asset.model or "",
            },
        }
