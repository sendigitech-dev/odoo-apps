{
    'name': 'AI Chat Assistant — Gemini, OpenAI, Claude',
    'version': '19.0.1.2.0',
    'category': 'Extra Tools',
    'summary': "Chat IA flottant dans Odoo avec contexte automatique — compatible Gemini, OpenAI et Claude.",
    'description': """
AI Chat Assistant — Gemini, OpenAI & Claude pour Odoo 19
=========================================================

Fonctionnalités :
-----------------
* **Chat flottant** accessible depuis toutes les pages Odoo (onglet fixe sur le bord droit)
* **Multi-LLM** : choisissez votre fournisseur IA — Google Gemini, OpenAI (ChatGPT) ou Anthropic (Claude)
* **Contexte automatique** : l'assistant détecte le module actif (CRM, Ventes, Comptabilité…)
  et injecte les données réelles dans chaque échange
* **Historique personnel** : chaque utilisateur a ses propres conversations persistantes
* **Mixin réutilisable** : héritez de ``senai.mixin`` dans vos modules pour ajouter
  des capacités IA en quelques lignes
* **Gestion des accès** : groupes Utilisateur / Administrateur intégrés
* **Zéro dépendance externe** : appels directs aux APIs IA via urllib (stdlib Python)

Prérequis :
-----------
* Une clé API au choix : Google Gemini (gratuit sur aistudio.google.com),
  OpenAI (platform.openai.com) ou Anthropic (console.anthropic.com)
* Odoo 19 Community ou Enterprise
    """,
    'author': 'SenDigiTech',
    'website': 'https://sendigitech.com',
    'support': 'contact@sendigitech.com',
    'depends': ['base', 'web'],
    'data': [
        'security/senai_security.xml',
        'security/ir.model.access.csv',
        'views/senai_config_views.xml',
        'views/senai_conversation_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'senai_connector/static/src/components/senai_chat_widget.xml',
            'senai_connector/static/src/components/senai_chat_widget.js',
            'senai_connector/static/src/components/senai_chat_widget.css',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'OPL-1',
    'price': 59,
    'currency': 'EUR',
}
