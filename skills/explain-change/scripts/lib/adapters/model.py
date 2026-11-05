"""The harness-neutral transcript model every adapter produces.

A Session is one agent conversation. Events are in file order; seq numbers them from 0 inside the
session. loc names the transcript line an event came from, so a quote can be traced back to it.
"""
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

USER_TEXT = 'user_text'            # typed by the human
ASSISTANT_TEXT = 'assistant_text'  # said by the agent
TOOL_CALL = 'tool_call'            # a tool the agent (or, with by_user, the human) ran
COMPACTION = 'compaction'          # the harness summarised earlier history
INJECTED = 'injected'              # text the harness or another agent put in the user channel
KINDS = (USER_TEXT, ASSISTANT_TEXT, TOOL_CALL, COMPACTION, INJECTED)

MAIN, SUBAGENT = 'main', 'subagent'


@dataclass
class Tool:
    call_id: Optional[str]
    name: Optional[str]
    is_shell: bool = False
    command: Optional[str] = None       # the shell command line, when the tool is a shell
    output: Optional[str] = None        # None while no matching output record exists
    exit_code: Optional[int] = None     # None when the harness recorded none
    is_error: bool = False              # non-zero exit code, or the harness marked the call as failed
    args: Any = None                    # the arguments as recorded (dict, or raw text for patch tools)
    by_user: bool = False               # the human ran it themselves (a `!command`)


@dataclass
class Event:
    kind: str
    seq: int
    ts: Optional[str] = None
    text: Optional[str] = None
    tool: Optional[Tool] = None
    loc: Optional[Tuple[str, int]] = None   # (file, line)


@dataclass
class Session:
    harness: str
    id: Optional[str]
    cwd: Optional[str] = None
    started_at: Optional[str] = None
    kind: str = MAIN
    parent_id: Optional[str] = None
    parent_call_id: Optional[str] = None    # the tool call in the parent that launched a subagent
    events: List[Event] = field(default_factory=list)
    children: List['Session'] = field(default_factory=list)

    def add(self, kind, ts=None, text=None, tool=None, loc=None):
        ev = Event(kind, len(self.events), ts, text, tool, loc)
        self.events.append(ev)
        return ev

    def walk(self):
        """This session, then its descendants."""
        yield self
        for c in self.children:
            yield from c.walk()
