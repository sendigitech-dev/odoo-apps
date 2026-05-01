from odoo import api, fields, models
from odoo.exceptions import UserError


class SenaiConfig(models.Model):
    _name = 'senai.config'
    _description = 'Configuration SenAI'

    name = fields.Char(
        string='Nom',
        default='Configuration principale',
        required=True,
    )
    provider = fields.Selection(
        selection=[
            ('gemini',    'Google Gemini'),
            ('openai',    'OpenAI (ChatGPT)'),
            ('anthropic', 'Anthropic (Claude)'),
        ],
        string='Fournisseur IA',
        default='gemini',
        required=True,
    )
    api_key = fields.Char(
        string='Clé API',
        help='Clé API du fournisseur IA sélectionné.',
    )
    model_id = fields.Char(
        string='Modèle',
        default='gemini-2.5-flash',
        help='Identifiant du modèle à utiliser.',
    )
    active = fields.Boolean(default=True)

    # ── Gestion des accès ────────────────────────────────────────────

    senai_user_ids = fields.Many2many(
        comodel_name='res.users',
        string='Utilisateurs SenAI',
        compute='_compute_senai_user_ids',
        inverse='_inverse_senai_user_ids',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Utilisateurs ayant accès au chat SenAI.',
    )
    senai_admin_ids = fields.Many2many(
        comodel_name='res.users',
        string='Administrateurs SenAI',
        compute='_compute_senai_admin_ids',
        inverse='_inverse_senai_admin_ids',
        domain=[('share', '=', False), ('active', '=', True)],
        help='Utilisateurs pouvant configurer SenAI et gérer les accès.',
    )

    @api.onchange('provider')
    def _onchange_provider(self):
        defaults = {
            'gemini':    'gemini-2.5-flash',
            'openai':    'gpt-4o',
            'anthropic': 'claude-opus-4-7',
        }
        self.model_id = defaults.get(self.provider, '')

    def _get_group(self, xml_id):
        return self.env.ref(xml_id, raise_if_not_found=False)

    def _compute_senai_user_ids(self):
        group = self._get_group('senai_connector.group_senai_user')
        users = group.user_ids if group else self.env['res.users']
        for rec in self:
            rec.senai_user_ids = users

    def _inverse_senai_user_ids(self):
        group = self._get_group('senai_connector.group_senai_user')
        if group and self:
            group.user_ids = self[0].senai_user_ids

    def _compute_senai_admin_ids(self):
        group = self._get_group('senai_connector.group_senai_admin')
        users = group.user_ids if group else self.env['res.users']
        for rec in self:
            rec.senai_admin_ids = users

    def _inverse_senai_admin_ids(self):
        group = self._get_group('senai_connector.group_senai_admin')
        if group and self:
            group.user_ids = self[0].senai_admin_ids

    # ── Méthode publique ─────────────────────────────────────────────

    @api.model
    def get_config(self):
        config = self.sudo().search([('active', '=', True)], limit=1)
        if not config:
            raise UserError(
                'Aucune configuration SenAI active. '
                'Renseignez votre clé API dans SenAI > Configuration.'
            )
        if not config.api_key:
            raise UserError(
                'Clé API manquante. '
                'Renseignez-la dans SenAI > Configuration.'
            )
        return config
