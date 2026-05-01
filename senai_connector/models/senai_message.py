from odoo import fields, models


class SenaiMessage(models.Model):
    _name = 'senai.message'
    _description = 'SenAI Message'
    _order = 'id asc'

    conversation_id = fields.Many2one(
        'senai.conversation',
        string='Conversation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    role = fields.Selection(
        selection=[('user', 'Utilisateur'), ('assistant', 'Assistant')],
        string='Rôle',
        required=True,
    )
    content = fields.Text(string='Contenu', required=True)
