"""
LLM Client for querying OpenAI with various prompts
"""

import os
import logging
from typing import Dict, List, Optional, Any
from openai import OpenAI
from datetime import datetime

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for LLM interactions with caching support"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o-mini-2024-07-18", 
                 temperature: float = 0.3, timeout: int = 300):
        """
        Initialize LLM client
        
        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4-turbo)
            temperature: Temperature for model (default: 0.3, lower = more deterministic)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key not found. Set OPENAI_API_KEY environment variable.")
        
        self.client = OpenAI(api_key=self.api_key, timeout=timeout)
        self.model = model
        self.temperature = temperature
        logger.info(f"LLMClient initialized with model: {model}")
    

    def query(self, prompt: str, text: str, system_role: str = "assistant") -> Optional[str]:
        """
        Query LLM with a single prompt and text
        
        Args:
            prompt: System prompt/instruction
            text: User text to analyze
            system_role: System role (default: "assistant")
            
        Returns:
            LLM response or None if failed
        """
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text}
        ]
        
        try:
            logger.info(f"Querying LLM with model {self.model}")
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                store=True,
                timeout=300
            )
            
            response_text = completion.choices[0].message.content
            tokens_used = completion.usage.total_tokens
            logger.info(f"LLM query successful. Tokens used: {tokens_used}")
            
            return response_text
            
        except Exception as e:
            logger.error(f"LLM query failed: {e}")
            return None
    

    def batch_query(self, prompts: Dict[str, str], text: str) -> Dict[str, Optional[str]]:
        """
        Query LLM with multiple prompts for the same text
        
        Args:
            prompts: Dict of {prompt_key: prompt_text}
            text: User text to analyze
            
        Returns:
            Dict of {prompt_key: response}
        """
        responses = {}
        
        for prompt_key, prompt_text in prompts.items():
            logger.info(f"Querying with prompt: {prompt_key}")
            response = self.query(prompt_text, text)
            responses[prompt_key] = response
        
        return responses
    

    def parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Attempt to parse JSON from LLM response
        
        Args:
            response: LLM response text
            
        Returns:
            Parsed JSON dict or None if parsing failed
        """
        import json
        
        if not response:
            return None
        
        try:
            # Try direct JSON parsing
            return json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            if "```json" in response:
                try:
                    json_str = response.split("```json")[1].split("```")[0].strip()
                    return json.loads(json_str)
                except (IndexError, json.JSONDecodeError):
                    pass
            
            # Try other code block formats
            if "```" in response:
                try:
                    json_str = response.split("```")[1].split("```")[0].strip()
                    # Remove language specifier if present
                    if json_str.startswith("json"):
                        json_str = json_str[4:].strip()
                    return json.loads(json_str)
                except (IndexError, json.JSONDecodeError):
                    pass
            
            logger.warning("Could not parse JSON from LLM response")
            return None
    

    def cache_response(self, responses_dict: Dict[str, Any], prompt_key: str, 
                      response: str, metadata: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Format response for caching
        
        Args:
            responses_dict: Existing responses dict to update
            prompt_key: Key identifying the prompt
            response: LLM response text
            metadata: Optional metadata to store with response
            
        Returns:
            Updated responses dict
        """
        entry = {
            "response": response,
            "queried_at": datetime.now().isoformat(),
            "model": self.model
        }
        
        if metadata:
            entry["metadata"] = metadata
        
        # Try to parse as JSON
        parsed = self.parse_json_response(response)
        if parsed:
            entry["parsed"] = parsed
        
        responses_dict[prompt_key] = entry
        return responses_dict

