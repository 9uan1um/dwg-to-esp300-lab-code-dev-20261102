"""Track coordinate/configuration epochs without any hardware interaction."""
import threading
from copy import deepcopy
import app_audit
from depth_recipe import default_context, fingerprint

class DepthContext:
    def __init__(self):
        self.lock=threading.RLock()
        self.revision=0
        self.last=None
        self.current=default_context()

    def observe(self, controller, axes, signs):
        # Passive snapshot only: never acquire controller locks or query positions.
        state={'local_offset':dict(controller.local_offset), 'home_ref':dict(controller.home_ref),
               'axis_numbers':dict(axes), 'legacy_axis_signs':dict(signs),
               'connection_generation':controller._poll_generation,
               'port':controller.port, 'baudrate':controller.baudrate, 'dry_run':controller.dry_run,
               'z_max_mm':controller.z_max_mm,'z_home_raw':controller.z_home_raw}
        digest=fingerprint(state)
        with self.lock:
            if self.last != digest:
                app_audit.RECORDER.reset_samples()
                previous=deepcopy(self.current)
                self.revision+=1
                self.current={**default_context(),**state,'origin_revision':self.revision}
                self.last=digest
                app_audit.emit('origin_or_configuration_changed',previous=previous,current=self.current,
                               depth_recipes_invalidated=True)
            return deepcopy(self.current)
