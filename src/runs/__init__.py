"""Durable execution for background work (WS-18).

SQL is the source of truth and Chroma is a rebuildable projection. The
public surface of this package is the queue (:mod:`src.runs.queue`), the
embedding handler (:mod:`src.runs.embedding`), the administration service
(:mod:`src.runs.service`) and the supervised worker (:mod:`src.runs.worker`).
"""
