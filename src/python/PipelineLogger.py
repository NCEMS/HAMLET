#!/usr/bin/env python3
"""
Minimal, robust event logger for pipeline execution tracking.
Writes atomic JSON lines to support concurrent access without locking.
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


class PipelineLogger:
    """
    Append-only logger that writes atomic JSON lines.
    Safe for concurrent writes from multiple processes.
    """
    
    def __init__(self, log_file_path: str, pxd_id: str):
        """
        Initialize logger.
        
        Args:
            log_file_path: Path to .jsonl file (will be created if needed)
            pxd_id: PXD identifier for context
        """
        self.log_file = Path(log_file_path)
        self.pxd_id = pxd_id
        self.start_time = datetime.utcnow().isoformat() + "Z"
        
        # Create parent directory if needed
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def _write_event(self, event: Dict[str, Any]) -> None:
        """Write single event as JSON line (atomic append)."""
        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(event) + '\n')
                f.flush()  # Ensure written to disk
        except Exception as e:
            print(f"[PipelineLogger] ERROR writing to {self.log_file}: {e}", file=sys.stderr)
    
    def _make_event(self, process: str, level: str, category: str, 
                    message: str, details: Optional[Dict] = None) -> Dict[str, Any]:
        """Create event dictionary with standard fields."""
        event = {
            "timestamp": (datetime.utcnow().isoformat() + "Z"),
            "pxd": self.pxd_id,
            "process": process,
            "level": level,
            "category": category,
            "message": message,
        }
        if details:
            event["details"] = details
        return event
    
    # Public API: Process lifecycle
    def process_start(self, process_name: str, details: Optional[Dict] = None) -> None:
        """Log process start."""
        event = self._make_event(process_name, "INFO", "lifecycle", f"Starting {process_name}", details)
        self._write_event(event)
    
    def process_step(self, process_name: str, step_name: str, details: Optional[Dict] = None) -> None:
        """Log process step."""
        event = self._make_event(process_name, "INFO", "step", f"Step: {step_name}", details)
        self._write_event(event)
    
    def process_decision(self, process_name: str, decision: str, reason: str, 
                        details: Optional[Dict] = None) -> None:
        """Log a process decision point."""
        msg = f"Decision: {decision} (reason: {reason})"
        event = self._make_event(process_name, "INFO", "decision", msg, details)
        self._write_event(event)
    
    def process_skip(self, process_name: str, reason: str, details: Optional[Dict] = None) -> None:
        """Log process skip."""
        msg = f"Skipped: {reason}"
        event = self._make_event(process_name, "WARNING", "skip", msg, details)
        self._write_event(event)
    
    def process_complete(self, process_name: str, status: str = "success", 
                        details: Optional[Dict] = None) -> None:
        """Log process completion."""
        level = "INFO" if status == "success" else "WARNING"
        msg = f"Completed: {status}"
        event = self._make_event(process_name, level, "lifecycle", msg, details)
        self._write_event(event)
    
    def process_error(self, process_name: str, error_msg: str, is_fatal: bool = False,
                     details: Optional[Dict] = None) -> None:
        """Log process error."""
        level = "ERROR" if is_fatal else "WARNING"
        event = self._make_event(process_name, level, "error", error_msg, details)
        self._write_event(event)
    
    # Public API: File operations
    def file_event(self, filename: str, step: str, status: str, 
                  details: Optional[Dict] = None) -> None:
        """Log file-level operation."""
        msg = f"File {filename}: {step} = {status}"
        level = "INFO" if status == "success" else "WARNING"
        event = self._make_event("file_operation", level, "file", msg, details)
        self._write_event(event)
    
    # Public API: Data observations (debug level)
    def debug(self, process_name: str, message: str, details: Optional[Dict] = None) -> None:
        """Log debug-level observation."""
        event = self._make_event(process_name, "DEBUG", "debug", message, details)
        self._write_event(event)


# Convenience function for scripts that just need to append
def log_event(log_file: str, pxd_id: str, process: str, level: str, category: str,
             message: str, details: Optional[Dict] = None) -> None:
    """Standalone function for single event logging (no class overhead)."""
    logger = PipelineLogger(log_file, pxd_id)
    event = logger._make_event(process, level, category, message, details)
    logger._write_event(event)
