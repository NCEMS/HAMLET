#!/usr/bin/env python
"""
Wrapper script for cascadia that pre-caches the Unimod database locally
to prevent network entity loading failures in lxml.
"""

import os
import sys
import shutil

# First, find and pre-populate the Unimod cache BEFORE cascadia imports pyteomics
def setup_unimod_cache():
    """Set up local Unimod database in pyteomics cache location."""
    # Find the local unimod file
    base_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(os.path.dirname(base_dir))
    local_unimod = os.path.join(repo_root, 'assets', 'unimod', 'unimod_tables.xml')
    
    if not os.path.exists(local_unimod):
        print(f"WARNING: Local Unimod file not found at {local_unimod}", file=sys.stderr)
        print("Cascadia will attempt to download from the internet", file=sys.stderr)
        return False
    
    # Set up cache directory
    cache_home = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
    os.makedirs(cache_home, exist_ok=True)
    
    pyteomics_cache = os.path.join(cache_home, 'pyteomics')
    os.makedirs(pyteomics_cache, exist_ok=True)
    
    # Copy local unimod to cache (with sanity checks)
    unimod_cache_file = os.path.join(pyteomics_cache, 'unimod_tables.xml')
    
    try:
        if not os.path.exists(unimod_cache_file) or os.path.getsize(unimod_cache_file) == 0:
            try:
                os.symlink(local_unimod, unimod_cache_file)
                print(f"[cascadia_wrapper] Symlinked Unimod DB: {local_unimod}", file=sys.stderr)
            except (OSError, FileExistsError):
                shutil.copy(local_unimod, unimod_cache_file)
                print(f"[cascadia_wrapper] Copied Unimod DB: {local_unimod}", file=sys.stderr)
        else:
            print(f"[cascadia_wrapper] Using cached Unimod DB: {unimod_cache_file}", file=sys.stderr)
        
        return True
    except Exception as e:
        print(f"[cascadia_wrapper] ERROR setting up Unimod cache: {e}", file=sys.stderr)
        return False


def monkeypatch_pyteomics():
    """Monkeypatch pyteomics.mass.unimod to use local Unimod file with caching fallback."""
    try:
        from pyteomics.mass import unimod as unimod_module
        
        # Store original load function
        original_load = unimod_module.load
        
        # Get cache location
        cache_home = os.environ.get('XDG_CACHE_HOME', os.path.expanduser('~/.cache'))
        local_cache = os.path.join(cache_home, 'pyteomics', 'unimod_tables.xml')
        
        def patched_load(doc_path, *args, **kwargs):
            """Try to load from local cache first, fall back to original load."""
            # If we're trying to load from a URL, try local cache first
            if isinstance(doc_path, str) and doc_path.startswith('http'):
                if os.path.exists(local_cache):
                    print(f"[cascadia_wrapper] Loading Unimod from local cache: {local_cache}", 
                          file=sys.stderr)
                    return original_load(local_cache, *args, **kwargs)
            
            # Otherwise use original load (local file or URL)
            return original_load(doc_path, *args, **kwargs)
        
        # Apply monkeypatch
        unimod_module.load = patched_load
        print(f"[cascadia_wrapper] Monkeypatched pyteomics.mass.unimod.load to use local cache", 
              file=sys.stderr)
        return True
        
    except Exception as e:
        print(f"[cascadia_wrapper] WARNING: Could not monkeypatch pyteomics: {e}", file=sys.stderr)
        return False


# Run setup and patching before cascadia imports anything
if __name__ == '__main__':
    # Set up cache first
    setup_unimod_cache()
    
    # Monkeypatch pyteomics 
    monkeypatch_pyteomics()
    
    # Now import and run cascadia
    print(f"[cascadia_wrapper] Starting cascadia with args: {sys.argv[1:]}", file=sys.stderr)
    
    try:
        from cascadia.cascadia import main
        sys.exit(main())
    except ImportError as e:
        print(f"ERROR: Could not import cascadia: {e}", file=sys.stderr)
        print("Make sure cascadia is installed in the conda environment", file=sys.stderr)
        sys.exit(1)
