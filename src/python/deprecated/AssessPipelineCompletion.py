#!/usr/bin/env python3
"""
Assess HAMLET annotator pipeline completion after a full run.

Checks:
1. ProteoWizard conversion success (.RAW/.WIFF → .mzML)
2. RunAssessor completion
3. De novo prediction (Casanovo/Cascadia) success
4. Organism identification completion
5. Modification site fractions population
6. SAGE/DIA-NN search completion (if enabled)

Generates summary report and detailed breakdown.
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime

class PipelineAssessor:
    def __init__(self, base_dir: str = "/mnt/storage_2/ProdPool7"):
        self.base_dir = Path(base_dir)
        self.results_dir = self.base_dir / "results"
        self.work_dir = self.base_dir / "work" / "downloads"
        self.pxds = []
        self.assessment = {}
        
    def discover_pxds(self) -> List[str]:
        """Find all PXD directories in results/."""
        pxds = []
        if self.results_dir.exists():
            for item in sorted(self.results_dir.iterdir()):
                if item.is_dir() and item.name.startswith("PXD"):
                    pxds.append(item.name)
        self.pxds = pxds
        return pxds
    
    def check_mzml_conversion(self, pxd: str) -> Dict[str, Any]:
        """
        Check .RAW/.WIFF files and corresponding .mzML conversions.
        
        Returns:
            {
                'raw_files': [list of .raw/.wiff files],
                'mzml_files': [list of .mzML files],
                'conversion_success_rate': float (0-1),
                'failed_conversions': [list of .raw files without .mzML],
                'details': str
            }
        """
        download_pxd_dir = self.work_dir / pxd
        result = {
            'raw_files': [],
            'mzml_files': [],
            'conversion_success_rate': 0,
            'failed_conversions': [],
            'details': 'Not checked'
        }
        
        if not download_pxd_dir.exists():
            result['details'] = "No download directory found"
            return result
        
        # Find all .raw and .wiff files
        raw_files = []
        for ext in ['*.raw', '*.RAW', '*.wiff', '*.WIFF']:
            raw_files.extend(download_pxd_dir.glob(f"**/{ext}"))
        
        result['raw_files'] = [str(f.name) for f in raw_files]
        
        # Find all .mzML files
        mzml_files = list(download_pxd_dir.glob("**/*.mzML"))
        result['mzml_files'] = [str(f.name) for f in mzml_files]
        
        # Assess conversion success
        if len(raw_files) > 0:
            result['conversion_success_rate'] = len(mzml_files) / len(raw_files)
            
            # Find which raw files don't have corresponding mzML
            for raw_file in raw_files:
                base_name = raw_file.stem
                mzml_expected = download_pxd_dir.rglob(f"{base_name}.mzML")
                if not list(mzml_expected):
                    result['failed_conversions'].append(raw_file.name)
        
        # Build summary
        if result['conversion_success_rate'] == 1.0 and len(raw_files) > 0:
            result['details'] = f"✓ All {len(raw_files)} files converted successfully"
        elif result['conversion_success_rate'] == 0:
            result['details'] = f"✗ No conversions: {len(raw_files)} .raw/.wiff files found, 0 .mzML"
        else:
            result['details'] = f"⚠ Partial: {len(mzml_files)}/{len(raw_files)} converted"
        
        return result
    
    def check_aggregated_results(self, pxd: str) -> Dict[str, Any]:
        """
        Check aggregated results JSON for populated sections.
        Counts actual de novo peptide predictions from .tsv files.
        
        Returns:
            {
                'file_exists': bool,
                'runAssessor_populated': bool,
                'organism_identification_populated': bool,
                'denovo_predictions_count': int,
                'modification_site_fractions_populated': bool,
                'search_results_populated': bool,
                'file_size_bytes': int,
                'details': str
            }
        """
        results_pxd_dir = self.results_dir / pxd
        json_path = results_pxd_dir / f"{pxd}_aggregated_results.json"
        
        result = {
            'file_exists': json_path.exists(),
            'runAssessor_populated': False,
            'organism_identification_populated': False,
            'denovo_predictions_count': 0,
            'organism_assigned_count': 0,
            'modification_site_fractions_populated': False,
            'search_results_populated': False,
            'file_size_bytes': 0,
            'details': 'File not found'
        }
        
        if not json_path.exists():
            return result
        
        try:
            result['file_size_bytes'] = json_path.stat().st_size
            
            with open(json_path, 'r') as f:
                data = json.load(f)
            
            # Check runAssessor
            if 'runAssessor' in data and data['runAssessor']:
                result['runAssessor_populated'] = bool(data['runAssessor'])
            
            # Check organism_identification
            if 'organism_identification' in data and data['organism_identification']:
                org_id = data['organism_identification']
                # Check if it has actual content (not just empty structure)
                if isinstance(org_id, dict) and len(org_id) > 0:
                    result['organism_identification_populated'] = True
                elif isinstance(org_id, list) and len(org_id) > 0:
                    result['organism_identification_populated'] = True
            
            # Count actual de novo peptide predictions from .tsv files in organism_results
            # These are the filtered Casanovo/Cascadia predictions, not the organism assignments
            denovo_count = 0
            organism_results_dir = results_pxd_dir / "organism_results"
            if organism_results_dir.exists():
                for tsv_file in organism_results_dir.rglob("*_filtered80pct_slim.tsv"):
                    try:
                        # Count lines (subtract 1 for header)
                        with open(tsv_file, 'r') as f:
                            lines = f.readlines()
                            if len(lines) > 1:  # More than just header
                                denovo_count += len(lines) - 1
                    except:
                        pass
            result['denovo_predictions_count'] = denovo_count
            
            # Count organism-assigned predictions from peptonizer_result.csv files
            # These are denovo peptides that were successfully mapped to organisms
            organism_assigned_count = 0
            if organism_results_dir.exists():
                for csv_file in organism_results_dir.rglob("peptonizer_result.csv"):
                    try:
                        # Count lines (subtract 1 for header)
                        with open(csv_file, 'r') as f:
                            lines = f.readlines()
                            if len(lines) > 1:  # More than just header
                                organism_assigned_count += len(lines) - 1
                    except:
                        pass
            result['organism_assigned_count'] = organism_assigned_count
            
            # Check modification_site_fractions
            if 'modification_site_fractions' in data and data['modification_site_fractions']:
                result['modification_site_fractions_populated'] = bool(data['modification_site_fractions'])
            
            # Check search results (SAGE or DIA-NN)
            if 'search_results' in data and data['search_results']:
                result['search_results_populated'] = bool(data['search_results'])
            
            # Build summary
            populated_sections = sum([
                result['runAssessor_populated'],
                result['organism_identification_populated'],
                result['denovo_predictions_count'] > 0,
                result['modification_site_fractions_populated'],
                result['search_results_populated']
            ])
            
            if populated_sections == 5:
                result['details'] = "✓ Complete: All sections populated"
            elif populated_sections == 0:
                result['details'] = "✗ Empty: No sections populated"
            else:
                result['details'] = f"⚠ Partial: {populated_sections}/5 sections with data"
        
        except json.JSONDecodeError as e:
            result['details'] = f"✗ Invalid JSON: {e}"
        except Exception as e:
            result['details'] = f"✗ Error reading file: {e}"
        
        return result
    
    def check_logs_for_errors(self, pxd: str) -> Dict[str, Any]:
        """Check work directory logs for specific error patterns."""
        result = {
            'organism_id_failed': False,
            'denovo_failed': False,
            'peptonizer_failed': False,
            'search_failed': False,
            'error_details': []
        }
        
        # Search work directory for PXD-specific task directories
        work_base = self.work_dir.parent  # /mnt/storage_2/ProdPool7/work
        
        # Look for organism_id task logs containing PXD
        for command_log in work_base.rglob("command.log"):
            try:
                with open(command_log, 'r') as f:
                    content = f.read()
                    
                # Simple check: if it's in a path containing PXD and has error patterns
                if pxd in str(command_log):
                    if 'organism_id' in str(command_log):
                        if 'ERROR' in content or 'error' in content or 'failed' in content.lower():
                            result['organism_id_failed'] = True
                            # Extract first error line
                            for line in content.split('\n'):
                                if 'error' in line.lower():
                                    result['error_details'].append(f"organism_id: {line[:100]}")
                                    break
                    
                    if 'denovo' in str(command_log):
                        if 'ERROR' in content or 'error' in content:
                            result['denovo_failed'] = True
            except:
                pass
        
        return result
    
    def run_full_assessment(self) -> Dict[str, Any]:
        """Run full assessment on all discovered PXDs."""
        print(f"Discovering PXDs in {self.results_dir}...")
        self.discover_pxds()
        print(f"Found {len(self.pxds)} PXDs: {', '.join(self.pxds)}\n")
        
        for pxd in self.pxds:
            print(f"Assessing {pxd}...", end=' ', flush=True)
            
            mzml_status = self.check_mzml_conversion(pxd)
            results_status = self.check_aggregated_results(pxd)
            log_errors = self.check_logs_for_errors(pxd)
            
            self.assessment[pxd] = {
                'mzml_conversion': mzml_status,
                'aggregated_results': results_status,
                'log_errors': log_errors
            }
            print("✓")
        
        return self.assessment
    
    def print_summary_table(self):
        """Print formatted summary table."""
        print("\n" + "="*180)
        print("PIPELINE COMPLETION SUMMARY")
        print("="*180)
        print()
        
        # Header
        print(f"{'PXD':<12} {'Conversion':<15} {'RunAssessor':<13} {'De Novo':<12} {'Org Assigned':<13} {'Org ID':<13} {'Mod Sites':<13} {'Overall Status':<20}")
        print("-"*180)
        
        # Rows
        for pxd in self.pxds:
            if pxd not in self.assessment:
                continue
            
            assess = self.assessment[pxd]
            
            # Conversion status
            conv_rate = assess['mzml_conversion']['conversion_success_rate']
            if conv_rate == 1.0:
                conv_str = "✓ 100%"
            elif conv_rate == 0:
                conv_str = "✗ 0%"
            else:
                conv_str = f"⚠ {conv_rate*100:.0f}%"
            
            # RunAssessor
            runassessor_str = "✓" if assess['aggregated_results']['runAssessor_populated'] else "✗"
            
            # De novo predictions (total)
            denovo_count = assess['aggregated_results']['denovo_predictions_count']
            if denovo_count > 0:
                denovo_str = f"✓ {denovo_count}"
            else:
                denovo_str = "✗ 0"
            
            # Organism assigned (peptonizer mapped)
            org_assigned_count = assess['aggregated_results']['organism_assigned_count']
            if org_assigned_count > 0:
                org_assigned_str = f"✓ {org_assigned_count}"
            else:
                org_assigned_str = "✗ 0"
            
            # Organism ID overall
            orgid_str = "✓" if assess['aggregated_results']['organism_identification_populated'] else "✗"
            
            # Mod sites
            modsites_str = "✓" if assess['aggregated_results']['modification_site_fractions_populated'] else "✗"
            
            # Overall status
            sections_populated = sum([
                assess['aggregated_results']['runAssessor_populated'],
                assess['aggregated_results']['organism_identification_populated'],
                denovo_count > 0,
                assess['aggregated_results']['modification_site_fractions_populated'],
                assess['aggregated_results']['search_results_populated']
            ])
            
            if sections_populated == 5:
                overall = "✓ COMPLETE"
            elif sections_populated >= 3:
                overall = "⚠ PARTIAL"
            else:
                overall = "✗ FAILED"
            
            print(f"{pxd:<12} {conv_str:<15} {runassessor_str:<13} {denovo_str:<12} {org_assigned_str:<13} {orgid_str:<13} {modsites_str:<13} {overall:<20}")
        
        print()
        print("="*180)
    
    def print_detailed_report(self):
        """Print detailed breakdown for each PXD."""
        print("\n" + "="*150)
        print("DETAILED BREAKDOWN")
        print("="*150)
        
        for pxd in sorted(self.pxds):
            if pxd not in self.assessment:
                continue
            
            assess = self.assessment[pxd]
            print(f"\n{pxd}")
            print("-"*80)
            
            # mzML conversion
            mzml = assess['mzml_conversion']
            print(f"  mzML Conversion: {mzml['details']}")
            if mzml['raw_files']:
                print(f"    Raw files: {len(mzml['raw_files'])} found")
                if mzml['failed_conversions']:
                    print(f"    Failed conversions: {', '.join(mzml['failed_conversions'][:3])}")
                    if len(mzml['failed_conversions']) > 3:
                        print(f"                      +{len(mzml['failed_conversions'])-3} more")
            
            # Aggregated results
            results = assess['aggregated_results']
            print(f"  Aggregated Results JSON: {results['details']}")
            if results['file_exists']:
                print(f"    File size: {results['file_size_bytes']/1024:.1f} KB")
                print(f"    RunAssessor: {'✓' if results['runAssessor_populated'] else '✗'}")
                print(f"    De novo predictions: {results['denovo_predictions_count']}")
                print(f"    Organism-assigned: {results['organism_assigned_count']}")
                print(f"    Organism ID: {'✓' if results['organism_identification_populated'] else '✗'}")
                print(f"    Modification sites: {'✓' if results['modification_site_fractions_populated'] else '✗'}")
                print(f"    Search results: {'✓' if results['search_results_populated'] else '✗'}")
            
            # Log errors
            logs = assess['log_errors']
            if logs['error_details']:
                print(f"  Errors detected:")
                for error in logs['error_details']:
                    print(f"    - {error}")
    
    def save_report(self, output_file: str = "pipeline_assessment.json"):
        """Save detailed assessment to JSON file."""
        output_path = self.base_dir / output_file
        
        # Convert Path objects to strings for JSON serialization
        export_data = {}
        for pxd, assessment in self.assessment.items():
            export_data[pxd] = assessment
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        print(f"\nDetailed assessment saved to: {output_path}")

def main():
    assessor = PipelineAssessor()
    assessor.run_full_assessment()
    assessor.print_summary_table()
    assessor.print_detailed_report()
    assessor.save_report()
    
    print(f"\n✓ Assessment complete at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    main()
