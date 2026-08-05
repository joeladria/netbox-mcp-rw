#!/usr/bin/env python3
"""
NetBox Client Library

This module provides a base class for NetBox client implementations and a REST API implementation.
"""

import abc
from typing import Any, Dict, List, Optional, Union
import requests


class NetBoxAPIError(requests.HTTPError):
    """
    Raised when a NetBox API request fails, with the response body's
    validation error details included in the exception message.

    NetBox's DRF-based API returns structured JSON on 4xx/5xx errors, e.g.:
        {"primary_ip4": ["Invalid pk \"3934\" - object does not exist."]}
    or, for some endpoints, a flat list of error strings. This exception
    surfaces that payload instead of just the HTTP status line.
    """

    def __init__(self, response: requests.Response):
        self.status_code = response.status_code
        self.url = response.url
        self.error_details = self._extract_error_details(response)
        super().__init__(self._build_message(response), response=response)

    @staticmethod
    def _extract_error_details(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    def _build_message(self, response: requests.Response) -> str:
        lines = [f"{self.status_code} {response.reason}: {self.url}"]

        details = self.error_details
        if isinstance(details, dict):
            for field, errors in details.items():
                if isinstance(errors, list):
                    errors = ", ".join(str(e) for e in errors)
                lines.append(f"  {field}: {errors}")
        elif isinstance(details, list):
            for error in details:
                lines.append(f"  {error}")
        elif details:
            lines.append(f"  {details}")

        return "\n".join(lines)


class NetBoxClientBase(abc.ABC):
    """
    Abstract base class for NetBox client implementations.
    
    This class defines the interface for CRUD operations that can be implemented
    either via the REST API or directly via the ORM in a NetBox plugin.
    """
    
    @abc.abstractmethod
    def get(
        self,
        endpoint: str,
        id: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Retrieve one or more objects from NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: Optional ID to retrieve a specific object
            params: Optional query parameters for filtering
            
        Returns:
            Either a single object dict or a list of object dicts
        """
        pass
    
    @abc.abstractmethod
    def create(self, endpoint: str, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Create a new object in NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: Object data to create
            
        Returns:
            The created object as a dict
        """
        pass
    
    @abc.abstractmethod
    def update(self, endpoint: str, id: int, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Update an existing object in NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: ID of the object to update
            data: Object data to update
            
        Returns:
            The updated object as a dict
        """
        pass
    
    @abc.abstractmethod
    def delete(self, endpoint: str, id: int, headers: Optional[Dict[str, str]] = None) -> bool:
        """
        Delete an object from NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: ID of the object to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        pass
    
    @abc.abstractmethod
    def bulk_create(self, endpoint: str, data: List[Dict[str, Any]], headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Create multiple objects in NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: List of object data to create
            
        Returns:
            List of created objects as dicts
        """
        pass
    
    @abc.abstractmethod
    def bulk_update(self, endpoint: str, data: List[Dict[str, Any]], headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Update multiple objects in NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: List of object data to update (must include ID)
            
        Returns:
            List of updated objects as dicts
        """
        pass
    
    @abc.abstractmethod
    def bulk_delete(self, endpoint: str, ids: List[int], headers: Optional[Dict[str, str]] = None) -> bool:
        """
        Delete multiple objects from NetBox.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            ids: List of IDs to delete
            
        Returns:
            True if deletion was successful, False otherwise
        """
        pass


class NetBoxRestClient(NetBoxClientBase):
    """
    NetBox client implementation using the REST API.
    """

# # Example of how to use the client
# client = NetBoxRestClient(
#     url="https://netbox.example.com",
#     token="your_api_token_here",
#     verify_ssl=True
# )
    
# # Get all sites
# sites = client.get("dcim/sites")
# print(f"Found {len(sites)} sites")
    
# # Get a specific site
# site = client.get("dcim/sites", id=1)
# print(f"Site name: {site.get('name')}")
    
# # Create a new site
# new_site = client.create("dcim/sites", {
#     "name": "New Site",
#     "slug": "new-site",
#     "status": "active"
# })
# print(f"Created site: {new_site.get('name')} (ID: {new_site.get('id')})")

    def __init__(self, url: str, token: str, verify_ssl: bool = True):
        """
        Initialize the REST API client.
        
        Args:
            url: The base URL of the NetBox instance (e.g., 'https://netbox.example.com')
            token: API token for authentication
            verify_ssl: Whether to verify SSL certificates
        """
        self.base_url = url.rstrip('/')
        self.api_url = f"{self.base_url}/api"
        self.token = token
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })
    
    def _build_url(self, endpoint: str, id: Optional[int] = None) -> str:
        """Build the full URL for an API request."""
        endpoint = endpoint.strip('/')
        if id is not None:
            return f"{self.api_url}/{endpoint}/{id}/"
        return f"{self.api_url}/{endpoint}/"

    def _handle_response(self, response: requests.Response) -> None:
        """
        Raise NetBoxAPIError (with response body details) if the response
        indicates an error, instead of a bare requests.HTTPError.
        """
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            raise NetBoxAPIError(response) from e
    
    def get(
        self,
        endpoint: str,
        id: Optional[int] = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Retrieve one or more objects from NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: Optional ID to retrieve a specific object
            params: Optional query parameters for filtering
            
        Returns:
            Either a single object dict or a list of object dicts
        
        Raises:
            requests.HTTPError: If the request fails
        """
        url = self._build_url(endpoint, id)
        response = self.session.get(url, params=params, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        
        data = response.json()
        if id is None and 'results' in data:
            # Handle paginated results
            return data['results']
        return data
    
    def create(self, endpoint: str, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Create a new object in NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: Object data to create
            
        Returns:
            The created object as a dict
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = self._build_url(endpoint)
        response = self.session.post(url, json=data, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.json()
    
    def update(self, endpoint: str, id: int, data: Dict[str, Any], headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Update an existing object in NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: ID of the object to update
            data: Object data to update
            
        Returns:
            The updated object as a dict
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = self._build_url(endpoint, id)
        response = self.session.patch(url, json=data, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.json()
    
    def delete(self, endpoint: str, id: int, headers: Optional[Dict[str, str]] = None) -> bool:
        """
        Delete an object from NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            id: ID of the object to delete
            
        Returns:
            True if deletion was successful, False otherwise
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = self._build_url(endpoint, id)
        response = self.session.delete(url, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.status_code == 204
    
    def bulk_create(self, endpoint: str, data: List[Dict[str, Any]], headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Create multiple objects in NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: List of object data to create
            
        Returns:
            List of created objects as dicts
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = f"{self._build_url(endpoint)}bulk/"
        response = self.session.post(url, json=data, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.json()
    
    def bulk_update(self, endpoint: str, data: List[Dict[str, Any]], headers: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """
        Update multiple objects in NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            data: List of object data to update (must include ID)
            
        Returns:
            List of updated objects as dicts
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = f"{self._build_url(endpoint)}bulk/"
        response = self.session.patch(url, json=data, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.json()
    
    def bulk_delete(self, endpoint: str, ids: List[int], headers: Optional[Dict[str, str]] = None) -> bool:
        """
        Delete multiple objects from NetBox via the REST API.
        
        Args:
            endpoint: The API endpoint (e.g., 'dcim/sites', 'ipam/prefixes')
            ids: List of IDs to delete
            
        Returns:
            True if deletion was successful, False otherwise
            
        Raises:
            requests.HTTPError: If the request fails
        """
        url = f"{self._build_url(endpoint)}bulk/"
        data = [{"id": id} for id in ids]
        response = self.session.delete(url, json=data, headers=headers, verify=self.verify_ssl)
        self._handle_response(response)
        return response.status_code == 204
