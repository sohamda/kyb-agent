"""Durable agent memory — procedural learnings only.

Mounts one deployment-shared tree at ``/memories/agent/``. Memory holds notes
about how the data behaves (for example how a registry reports ownership). It
must never hold personal, customer or application data; see the memory policy in
``instructions.md``.
"""

from managed_deepagents import MemoryLayer, define_memory

memory = define_memory(agent=MemoryLayer())
