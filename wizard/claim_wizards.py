from odoo import fields, models


class ClaimRejectWizard(models.TransientModel):
    """Wizard for rejecting warranty claims with a reason."""

    _name = "assetz.claim.reject.wizard"
    _description = "Claim Rejection Wizard"

    claim_id = fields.Many2one(
        comodel_name="assetz.warranty.claim",
        string="Claim",
        required=True,
    )
    reason = fields.Text(
        string="Rejection Reason",
        required=True,
    )

    def action_reject(self):
        """Reject the claim with the provided reason."""
        self.claim_id.write(
            {
                "state": "rejected",
                "rejection_reason": self.reason,
            }
        )
        return {"type": "ir.actions.act_window_close"}


class ClaimPartialApproveWizard(models.TransientModel):
    """Wizard for partially approving warranty claims."""

    _name = "assetz.claim.partial.approve.wizard"
    _description = "Claim Partial Approval Wizard"

    claim_id = fields.Many2one(
        comodel_name="assetz.warranty.claim",
        string="Claim",
        required=True,
    )
    total_claimed = fields.Monetary(
        related="claim_id.total_claimed_amount",
        string="Total Claimed",
    )
    approved_amount = fields.Monetary(
        string="Approved Amount",
        required=True,
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="claim_id.currency_id",
    )
    response = fields.Text(
        string="Response/Notes",
        help="Explanation for partial approval",
    )

    def action_partial_approve(self):
        """Partially approve the claim with the specified amount."""
        self.claim_id.write(
            {
                "state": "partially_approved",
                "approved_amount": self.approved_amount,
                "provider_response": self.response,
            }
        )
        return {"type": "ir.actions.act_window_close"}
