from odoo import api, fields, models
from odoo.exceptions import UserError


class CreateAssetsWizard(models.TransientModel):
    """Wizard to create assets from a purchase request."""

    _name = "assetz.create.assets.wizard"
    _description = "Create Assets from Purchase"

    purchase_request_id = fields.Many2one(
        comodel_name="assetz.purchase.request",
        string="Purchase Request",
        required=True,
    )
    category_id = fields.Many2one(
        related="purchase_request_id.category_id",
        string="Category",
    )
    quantity = fields.Integer(
        related="purchase_request_id.quantity",
        string="Total Quantity",
    )
    supplier_id = fields.Many2one(
        related="purchase_request_id.supplier_id",
        string="Supplier",
    )

    line_ids = fields.One2many(
        comodel_name="assetz.create.assets.wizard.line",
        inverse_name="wizard_id",
        string="Assets to Create",
    )

    @api.model
    def default_get(self, fields_list):
        """Pre-populate lines based on quantity."""
        res = super().default_get(fields_list)

        if "purchase_request_id" in self._context:
            purchase_request = self.env["assetz.purchase.request"].browse(
                self._context.get("purchase_request_id")
            )
            if purchase_request.exists():
                res["purchase_request_id"] = purchase_request.id

                # Create lines for each asset
                lines = []
                for i in range(purchase_request.quantity):
                    lines.append((0, 0, {
                        "name": f"{purchase_request.category_id.name} - {purchase_request.name} #{i + 1}",
                        "serial_number": "",
                        "acquisition_cost": purchase_request.estimated_unit_cost,
                    }))
                res["line_ids"] = lines

        return res

    def action_create_assets(self):
        """Create the assets from the wizard lines."""
        self.ensure_one()

        if not self.line_ids:
            raise UserError("Please add at least one asset to create.")

        created_assets = self.env["assetz.asset"]
        for line in self.line_ids:
            if not line.name:
                raise UserError("All assets must have a name.")

            asset_vals = {
                "name": line.name,
                "category_id": self.category_id.id,
                "serial_number": line.serial_number,
                "supplier_id": self.supplier_id.id,
                "acquisition_date": fields.Date.today(),
                "acquisition_cost": line.acquisition_cost,
                "location_id": line.location_id.id if line.location_id else False,
                "purchase_request_id": self.purchase_request_id.id,
                "state": "draft",
            }
            # Link to source asset request if available
            if self.purchase_request_id.asset_request_id:
                asset_vals["source_asset_request_id"] = self.purchase_request_id.asset_request_id.id
            asset = self.env["assetz.asset"].create(asset_vals)
            created_assets |= asset

        # Update purchase request state
        self.purchase_request_id.state = "received"

        # Update source asset request to assets_ready state (not fulfilled yet)
        if self.purchase_request_id.asset_request_id:
            self.purchase_request_id.asset_request_id.state = "assets_ready"

        # Return action to view created assets
        if len(created_assets) == 1:
            return {
                "type": "ir.actions.act_window",
                "name": "Created Asset",
                "res_model": "assetz.asset",
                "view_mode": "form",
                "res_id": created_assets.id,
            }
        else:
            return {
                "type": "ir.actions.act_window",
                "name": "Created Assets",
                "res_model": "assetz.asset",
                "view_mode": "list,form",
                "domain": [("id", "in", created_assets.ids)],
            }


class CreateAssetsWizardLine(models.TransientModel):
    """Line for each asset to create."""

    _name = "assetz.create.assets.wizard.line"
    _description = "Create Assets Wizard Line"

    wizard_id = fields.Many2one(
        comodel_name="assetz.create.assets.wizard",
        string="Wizard",
        required=True,
        ondelete="cascade",
    )
    name = fields.Char(
        string="Asset Name",
        required=True,
    )
    serial_number = fields.Char(
        string="Serial Number",
    )
    acquisition_cost = fields.Float(
        string="Acquisition Cost",
    )
    location_id = fields.Many2one(
        comodel_name="assetz.location",
        string="Initial Location",
    )
