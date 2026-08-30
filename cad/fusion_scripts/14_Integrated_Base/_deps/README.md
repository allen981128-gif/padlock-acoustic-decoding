# Frozen source dependencies

These modules are explicit copies of the source snapshots that were embedded inside the parent Fusion script before the P3 cleanup. They are kept local to the parent script because some snapshots differ from the separately listed component scripts elsewhere in the repository.

Do not replace these files with similarly named component scripts unless the resulting Fusion geometry is regression-tested. The parent script loads them with `importlib` and overrides `silent_message_box` to preserve the previous popup-suppression behaviour.
