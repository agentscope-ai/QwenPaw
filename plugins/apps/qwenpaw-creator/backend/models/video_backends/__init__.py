# -*- coding: utf-8 -*-
"""Provider-specific video generation protocol modules.

Each module owns the wire format of one non-DashScope video backend:
``build_submit_request()`` renders (url, headers, body) for the shared
submit shell in ``models.video_model``, ``extract_task_id()`` reads the
provider's task handle from the accepted response, and ``check_status()``
polls the task into the shared ``{task_id, status, result_url?, error?}``
shape consumed by the R2V execution service.
"""
