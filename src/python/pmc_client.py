"""
PubMed Central API Client for fetching publication metadata and full text
"""

import logging
import requests
import subprocess
import os
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class PMCClient:
    """Client for PMC (PubMed Central) API interactions"""
    
    def __init__(self, email: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 30):
        """
        Initialize PMC client
        
        Args:
            email: Email for NCBI API requests (recommended for higher rate limits)
            api_key: NCBI API key (optional, for higher rate limits)
            timeout: Request timeout in seconds
        """
        self.email = email
        self.api_key = api_key
        self.timeout = timeout
        self.idconv_url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
        self.bioc_base = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi"
        self.supp_base = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/supplmat.cgi"
    
    def pmid_to_pmcid(self, pmid: str) -> Optional[str]:
        """
        Convert PubMed ID to PubMed Central ID
        
        Args:
            pmid: PubMed ID
            
        Returns:
            PMCID (e.g., "PMC1234567") or None if not found
        """
        params = {"ids": str(pmid), "format": "json"}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        logger.info(f"Converting PMID {pmid} to PMCID using NCBI ID Converter: {params}")

        try:
            logger.info(f"Converting PMID {pmid} to PMCID")
            response = requests.get(self.idconv_url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            # print(data)
            
            records = data.get("records", [])
            if not records:
                logger.warning(f"No PMCID found for PMID {pmid}")
                return None
            
            # Check if the first record has an error status (e.g., paper not in PMC)
            first_record = records[0]
            if first_record.get("status") == "error":
                errmsg = first_record.get("errmsg", "Unknown error")
                logger.warning(f"PMID {pmid} conversion failed: {errmsg}")
                return None
            
            pmcid = first_record.get("pmcid")
            if not pmcid:
                logger.warning(f"No PMCID in response for PMID {pmid}")
                return None
                
            logger.info(f"PMID {pmid} -> PMCID {pmcid}")
            return pmcid
        except requests.RequestException as e:
            logger.error(f"Failed to convert PMID {pmid} to PMCID: {e}")
            return None

    
    def fetch_full_text(self, pmcid: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full text in BioC JSON format
        
        Args:
            pmcid: PubMed Central ID
            
        Returns:
            BioC JSON dict or None if failed
        """
        url = f"{self.bioc_base}/BioC_json/{pmcid}/unicode"
        
        try:
            logger.info(f"Fetching full text for PMCID {pmcid}")
            response = requests.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch full text for PMCID {pmcid}: {e}")
            return None
    
    def fetch_supplementary_files(self, pmcid: str) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch supplementary files list
        
        Args:
            pmcid: PubMed Central ID
            
        Returns:
            List of supplementary file metadata or None if failed
        """
        url = f"{self.supp_base}/bioc_json/{pmcid}/list"
        
        try:
            logger.info(f"Fetching supplementary files for PMCID {pmcid}")
            response = requests.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            response.raise_for_status()
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"Failed to fetch supplementary files for PMCID {pmcid}: {e}")
            return None
    
    def download_supplementary_file(self, bioc_url: str, output_path: str) -> bool:
        """
        Download a supplementary file from BioC URL
        
        Args:
            bioc_url: URL to the supplementary file
            output_path: Local path to save file
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Downloading supplementary file: {output_path}")
            result = subprocess.run(
                ["wget", bioc_url, "-O", output_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"wget failed: {result.stderr}")
                return False
            
            # Check if file is empty
            if os.path.exists(output_path) and os.path.getsize(output_path) == 0:
                logger.warning(f"Downloaded file is empty: {output_path}")
                os.remove(output_path)
                return False
            
            logger.info(f"Successfully downloaded: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to download supplementary file: {e}")
            return False
    
    def extract_text_sections(self, bioc_json: Dict[str, Any]) -> Dict[str, str]:
        """
        Extract major text sections from BioC JSON
        
        Args:
            bioc_json: BioC JSON response from fetch_full_text
            
        Returns:
            Dict with keys: title, abstract, introduction, methods, results, discussion
        """
        sections = {
            "title": "",
            "abstract": "",
            "results": "",
            "methods": "",
        }
        
        try:
            for bioc in bioc_json:
                for document in bioc.get("documents", []):
                    for passage in document.get("passages", []):
                        section_type = passage.get("infons", {}).get("section_type", "").lower()
                        text = passage.get("text", "")
                        print(f"Section type: {section_type}, text length: {len(text)}")
                        if section_type in sections:
                            sections[section_type] += text + "\n"
            
            logger.info(f"Extracted sections: {list(k for k, v in sections.items() if v)}")
            return sections
            
        except Exception as e:
            logger.error(f"Failed to extract text sections: {e}")
            return sections
