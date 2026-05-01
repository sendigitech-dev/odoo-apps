import json
import urllib.request
import urllib.error
from odoo import api, fields, models
from odoo.exceptions import UserError

_GEMINI_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'
_GEMINI_FALLBACKS = ['gemini-2.0-flash', 'gemini-2.5-flash-lite']


class SenaiConversation(models.Model):
    _name = 'senai.conversation'
    _description = 'SenAI Conversation'
    _order = 'write_date desc'
    _rec_name = 'name'

    name = fields.Char(string='Titre', default='Nouvelle conversation')
    user_id = fields.Many2one(
        'res.users',
        string='Utilisateur',
        default=lambda self: self.env.user,
        required=True,
        index=True,
        ondelete='cascade',
    )
    context_model = fields.Char(string='Modèle Odoo')
    context_label = fields.Char(string='Module')
    message_ids = fields.One2many('senai.message', 'conversation_id', string='Messages')
    message_count = fields.Integer(compute='_compute_message_count', store=True)

    @api.depends('message_ids')
    def _compute_message_count(self):
        for rec in self:
            rec.message_count = len(rec.message_ids)

    # ─── API publique appelée par le widget ────────────────────────────

    @api.model
    def get_conversations(self):
        convs = self.search([('user_id', '=', self.env.user.id)], limit=40)
        return [
            {
                'id': c.id,
                'name': c.name,
                'context_label': c.context_label or '',
                'message_count': c.message_count,
                'date': fields.Datetime.to_string(c.write_date)[:16].replace('T', ' ') if c.write_date else '',
            }
            for c in convs
        ]

    @api.model
    def get_messages(self, conversation_id):
        conv = self.browse(conversation_id)
        if conv.user_id.id != self.env.user.id:
            raise UserError("Accès refusé.")
        return [
            {'role': m.role, 'content': m.content}
            for m in conv.message_ids.sorted('id')
        ]

    @api.model
    def send_message(self, conversation_id, prompt, context_model=None, context_label=None):
        SenaiMessage = self.env['senai.message']

        if conversation_id:
            conv = self.browse(conversation_id)
            if conv.user_id.id != self.env.user.id:
                raise UserError("Accès refusé.")
        else:
            conv = self.create({
                'name': (prompt or '')[:60] or 'Nouvelle conversation',
                'user_id': self.env.user.id,
                'context_model': context_model,
                'context_label': context_label,
            })

        SenaiMessage.create({
            'conversation_id': conv.id,
            'role': 'user',
            'content': prompt,
        })

        # Historique neutre — chaque provider le convertit dans son format
        messages = [
            {'role': m.role, 'content': m.content}
            for m in conv.message_ids.sorted('id')
        ]

        system_prompt = self._build_system_prompt(
            context_model or conv.context_model,
            context_label or conv.context_label,
        )

        config = self.env['senai.config'].get_config()
        answer = self._call_ai(config, messages, system_prompt)

        SenaiMessage.create({
            'conversation_id': conv.id,
            'role': 'assistant',
            'content': answer,
        })

        return {
            'conversation_id': conv.id,
            'conversation_name': conv.name,
            'answer': answer,
        }

    @api.model
    def delete_conversation(self, conversation_id):
        conv = self.browse(conversation_id)
        if conv.user_id.id != self.env.user.id:
            raise UserError("Accès refusé.")
        conv.unlink()
        return True

    # ─── Contexte Odoo ─────────────────────────────────────────────────

    def _build_system_prompt(self, context_model, context_label):
        user = self.env.user
        parts = [
            "Tu es SenAI, l'assistant IA intégré dans Odoo.",
            f"L'utilisateur connecté est {user.name}.",
            "Tu réponds en français. Tu es concis et précis.",
        ]

        if context_model and context_label:
            data = self._fetch_context_data(context_model)
            if data:
                parts.append(
                    f"Tu as accès aux données du module **{context_label}** uniquement.\n"
                    f"Si l'utilisateur pose une question sur un autre module, "
                    f"dis-lui que tu n'as pas ces données en contexte et invite-le à naviguer vers ce module.\n"
                    f"\nDonnées actuelles du module {context_label} :\n{data}"
                )
            else:
                parts.append(
                    f"L'utilisateur est dans le module **{context_label}** "
                    f"mais aucune donnée n'est disponible (module vide ou non installé).\n"
                    f"Réponds quand même aux questions générales sur ce module Odoo. "
                    f"Ne demande pas à l'utilisateur de naviguer ou de charger des données — "
                    f"tu es un assistant textuel, pas une interface graphique."
                )
        else:
            parts.append(
                "Tu n'es dans aucun module Odoo spécifique. "
                "Tu peux répondre aux questions générales sur Odoo."
            )

        return '\n'.join(parts)

    _MODEL_DOMAINS = {
        'crm.lead':       lambda uid: [('user_id', '=', uid)],
        'sale.order':     lambda uid: [],
        'account.move':   lambda uid: [],
        'project.task':   lambda uid: [],
        'hr.employee':    lambda uid: [],
        'purchase.order': lambda uid: [],
        'stock.picking':  lambda uid: [],
    }

    def _fetch_context_data(self, model_name):
        try:
            Model = self.env.get(model_name)
            if not Model:
                return f"Le module Odoo lié ({model_name}) n'est pas installé sur cette instance."

            domain_fn = self._MODEL_DOMAINS.get(model_name)
            domain = domain_fn(self.env.user.id) if domain_fn else []

            records = Model.search(domain, limit=500)
            if not records:
                return "Aucun enregistrement trouvé."

            handlers = {
                'crm.lead':       self._ctx_crm,
                'sale.order':     self._ctx_sales,
                'account.move':   self._ctx_accounting,
                'project.task':   self._ctx_tasks,
                'hr.employee':    self._ctx_hr,
                'purchase.order': self._ctx_purchase,
                'stock.picking':  self._ctx_stock,
            }
            handler = handlers.get(model_name)
            if handler:
                lines = handler(records)
            elif 'name' in Model._fields:
                lines = [f"Total : {len(records)} enregistrement(s)."]
                names = [r.name for r in records[:5] if r.name]
                if names:
                    lines.append(f"Exemples : {', '.join(names)}")
            else:
                lines = [f"Total : {len(records)} enregistrement(s)."]

            return '\n'.join(lines)
        except Exception:
            return None

    def _ctx_crm(self, records):
        lines = []
        total_rev = sum(r.expected_revenue or 0 for r in records)
        lines.append(f"Revenu attendu total : {total_rev:,.0f}")
        by_stage = {}
        for r in records:
            s = r.stage_id.name if r.stage_id else 'Sans étape'
            by_stage[s] = by_stage.get(s, 0) + 1
        for s, n in sorted(by_stage.items(), key=lambda x: -x[1])[:6]:
            lines.append(f"  - {s} : {n} lead(s)")
        return lines

    def _ctx_sales(self, records):
        total = sum(r.amount_total for r in records)
        labels = {'draft': 'Brouillon', 'sent': 'Envoyé', 'sale': 'Confirmé',
                  'done': 'Livré', 'cancel': 'Annulé'}
        by_state = {}
        for r in records:
            by_state[r.state] = by_state.get(r.state, 0) + 1
        lines = [f"Montant total : {total:,.2f}"]
        for s, n in by_state.items():
            lines.append(f"  - {labels.get(s, s)} : {n}")
        return lines

    def _ctx_accounting(self, records):
        out_inv = records.filtered(lambda r: r.move_type == 'out_invoice')
        in_inv  = records.filtered(lambda r: r.move_type == 'in_invoice')
        out_ref = records.filtered(lambda r: r.move_type == 'out_refund')
        in_ref  = records.filtered(lambda r: r.move_type == 'in_refund')

        pay_labels = {
            'not_paid': 'impayée', 'partial': 'partielle',
            'paid': 'payée', 'in_payment': 'en cours',
            'reversed': 'annulée', 'blocked': 'bloquée',
        }

        def state_summary(moves):
            counts = {}
            for m in moves:
                counts[m.payment_state] = counts.get(m.payment_state, 0) + 1
            return ', '.join(f"{pay_labels.get(s, s)}: {n}" for s, n in counts.items())

        lines = [
            f"Factures clients : {len(out_inv)} "
            f"(montant TTC : {sum(r.amount_total for r in out_inv):,.2f})",
        ]
        if out_inv:
            lines.append(f"  État paiement : {state_summary(out_inv)}")
        lines.append(
            f"Factures fournisseurs : {len(in_inv)} "
            f"(montant TTC : {sum(r.amount_total for r in in_inv):,.2f})"
        )
        if in_inv:
            lines.append(f"  État paiement : {state_summary(in_inv)}")
        if out_ref:
            lines.append(f"Avoirs clients : {len(out_ref)}")
        if in_ref:
            lines.append(f"Avoirs fournisseurs : {len(in_ref)}")
        return lines

    def _ctx_tasks(self, records):
        by_stage = {}
        for r in records:
            s = r.stage_id.name if r.stage_id else 'Sans étape'
            by_stage[s] = by_stage.get(s, 0) + 1
        return [f"  - {s} : {n} tâche(s)"
                for s, n in sorted(by_stage.items(), key=lambda x: -x[1])[:6]]

    def _ctx_hr(self, records):
        by_dept = {}
        for r in records:
            d = r.department_id.name if r.department_id else 'Sans département'
            by_dept[d] = by_dept.get(d, 0) + 1
        return [f"  - {d} : {n} employé(s)"
                for d, n in sorted(by_dept.items(), key=lambda x: -x[1])[:6]]

    def _ctx_purchase(self, records):
        total = sum(r.amount_total for r in records)
        return [f"Montant total achats : {total:,.2f}"]

    def _ctx_stock(self, records):
        by_state = {}
        for r in records:
            by_state[r.state] = by_state.get(r.state, 0) + 1
        return [f"  - {s} : {n}" for s, n in by_state.items()]

    # ─── Dispatcher multi-LLM ──────────────────────────────────────────

    def _call_ai(self, config, messages, system_prompt):
        if config.provider == 'openai':
            return self._call_openai(config, messages, system_prompt)
        elif config.provider == 'anthropic':
            return self._call_anthropic(config, messages, system_prompt)
        else:
            return self._call_gemini(config, messages, system_prompt)

    def _call_gemini(self, config, messages, system_prompt):
        # Convertit le format neutre vers le format Gemini
        history = [
            {
                'role': 'user' if m['role'] == 'user' else 'model',
                'parts': [{'text': m['content']}],
            }
            for m in messages
        ]
        payload = {'contents': history}
        if system_prompt:
            payload['systemInstruction'] = {'parts': [{'text': system_prompt}]}

        models_to_try = [config.model_id] + [
            m for m in _GEMINI_FALLBACKS if m != config.model_id
        ]

        for model in models_to_try:
            url = f'{_GEMINI_BASE}/{model}:generateContent?key={config.api_key}'
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return result['candidates'][0]['content']['parts'][0]['text']
            except urllib.error.HTTPError as e:
                body = e.read().decode('utf-8')
                if e.code in (429, 503) and model != models_to_try[-1]:
                    continue
                raise UserError(self._friendly_error('Gemini', e.code, body))
            except urllib.error.URLError:
                raise UserError("Impossible de joindre l'API Gemini. Vérifiez votre connexion.")

    def _call_openai(self, config, messages, system_prompt):
        oai_messages = []
        if system_prompt:
            oai_messages.append({'role': 'system', 'content': system_prompt})
        oai_messages += [{'role': m['role'], 'content': m['content']} for m in messages]

        payload = {
            'model': config.model_id or 'gpt-4o',
            'messages': oai_messages,
            'max_tokens': 4096,
        }
        req = urllib.request.Request(
            'https://api.openai.com/v1/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {config.api_key}',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except urllib.error.HTTPError as e:
            raise UserError(self._friendly_error('OpenAI', e.code, e.read().decode('utf-8')))
        except urllib.error.URLError:
            raise UserError("Impossible de joindre l'API OpenAI. Vérifiez votre connexion.")

    def _call_anthropic(self, config, messages, system_prompt):
        payload = {
            'model': config.model_id or 'claude-opus-4-7',
            'max_tokens': 4096,
            'messages': [{'role': m['role'], 'content': m['content']} for m in messages],
        }
        if system_prompt:
            payload['system'] = system_prompt

        req = urllib.request.Request(
            'https://api.anthropic.com/v1/messages',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'x-api-key': config.api_key,
                'anthropic-version': '2023-06-01',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result['content'][0]['text']
        except urllib.error.HTTPError as e:
            raise UserError(self._friendly_error('Anthropic', e.code, e.read().decode('utf-8')))
        except urllib.error.URLError:
            raise UserError("Impossible de joindre l'API Anthropic. Vérifiez votre connexion.")

    def _friendly_error(self, provider, code, body):
        generic = {
            401: f"Clé API {provider} invalide. Vérifiez-la dans SenAI > Configuration.",
            403: f"Accès refusé par l'API {provider}. Vérifiez les droits de votre clé.",
            429: f"Quota API {provider} dépassé. Réessayez dans quelques minutes.",
            500: f"Erreur interne du serveur {provider}. Réessayez plus tard.",
            503: f"Service {provider} temporairement indisponible. Réessayez dans un instant.",
        }
        if code in generic:
            return generic[code]
        try:
            msg = json.loads(body).get('error', {}).get('message', body)
        except Exception:
            msg = body
        return f'Erreur API {provider} ({code}) : {msg}'
