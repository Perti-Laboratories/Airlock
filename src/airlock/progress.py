"""Ephemeral bounded turn progress. Saved replies retain their completed trace separately."""
import copy
import threading
import time
from .memory import ActionError


class TurnProgress:
    def __init__(self):
        self.lock=threading.Lock()
        self.turns={}

    def start(self, ident):
        with self.lock:
            cutoff=time.monotonic()-1800
            self.turns={k:v for k,v in self.turns.items() if v['at']>cutoff}
            if ident in self.turns: raise ActionError('This chat request has already been received. Refresh the feed before retrying.')
            if len(self.turns)>=64:
                oldest=next((k for k,v in self.turns.items() if v['status']!='running'),None)
                if oldest is None: raise ActionError('Chat progress is full. Retry shortly.')
                del self.turns[oldest]
            self.turns[ident]={'at':time.monotonic(),'status':'running','steps':[]}

    def update(self, ident, steps):
        with self.lock:
            self.turns[ident]['steps']=copy.deepcopy(steps)
            self.turns[ident]['at']=time.monotonic()

    def finish(self, ident, status):
        with self.lock: self.turns[ident]['status']=status

    def get(self, ident):
        with self.lock:
            row=self.turns.get(ident)
            return copy.deepcopy({'status':row['status'],'steps':row['steps']}) if row else None
