from odoo import api, fields, models
from odoo.exceptions import UserError


class AssetzSignatureWizard(models.TransientModel):
    """Wizard for capturing digital signatures on maintenance orders."""

    _name = "assetz.signature.wizard"
    _description = "Signature Wizard"

    order_id = fields.Many2one(
        comodel_name="assetz.maintenance.order",
        string="Maintenance Order",
        required=True,
    )
    signature_type = fields.Selection(
        selection=[
            ("technician", "Technician"),
            ("customer", "Customer/Manager"),
        ],
        string="Signature Type",
        required=True,
    )
    signature = fields.Binary(
        string="Signature",
        required=True,
    )

    # Technician fields
    technician_id = fields.Many2one(
        comodel_name="hr.employee",
        string="Technician",
        default=lambda self: self._get_default_technician(),
    )

    # Customer fields
    customer_name = fields.Char(
        string="Name",
    )

    @api.model
    def _get_default_technician(self):
        """Get current user's employee record as default technician."""
        employee = self.env["hr.employee"].search(
            [("user_id", "=", self.env.uid)], limit=1
        )
        return employee.id if employee else False

    @api.onchange("signature_type")
    def _onchange_signature_type(self):
        """Set defaults based on signature type."""
        if self.signature_type == "technician":
            self.technician_id = self._get_default_technician()
            self.customer_name = False
        else:
            self.technician_id = False

    def action_save_signature(self):
        """Save the signature to the maintenance order."""
        self.ensure_one()

        if not self.signature:
            raise UserError("Please provide a signature.")

        if self.signature_type == "technician":
            if not self.technician_id:
                raise UserError("Please select the technician.")

            self.order_id.write(
                {
                    "technician_signature": self.signature,
                    "technician_signed_by": self.technician_id.id,
                    "technician_signed_date": fields.Datetime.now(),
                }
            )
        else:
            if not self.customer_name:
                raise UserError("Please enter the customer/manager name.")

            self.order_id.write(
                {
                    "customer_signature": self.signature,
                    "customer_signed_name": self.customer_name,
                    "customer_signed_date": fields.Datetime.now(),
                }
            )

        return {"type": "ir.actions.act_window_close"}
