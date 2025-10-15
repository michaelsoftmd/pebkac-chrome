"""Browser utility functions for zendriver operations."""

import logging

logger = logging.getLogger(__name__)


async def safe_evaluate(tab, expression: str):
    """
    Safe wrapper for tab.evaluate that properly handles zendriver's return behavior.
    
    Zendriver's evaluate() returns (remote_object, errors) tuple when remote_object.value 
    is falsy, even with return_by_value=True. This wrapper ensures we always get the 
    actual JavaScript return value.
    """
    try:
        result = await tab.evaluate(expression, return_by_value=True)
        
        # Handle all tuple cases
        if isinstance(result, tuple):
            remote_object, errors = result
            if errors:
                logger.error(f"JavaScript evaluation error: {errors}")
                return None
            
            # Check for RemoteObject with value attribute
            if hasattr(remote_object, 'value'):
                # This includes None, empty strings, 0, False
                return remote_object.value
            
            # Try to get string representation
            if hasattr(remote_object, '__str__'):
                return str(remote_object)
            
            return None
        
        # Direct return for non-tuple results
        return result
        
    except Exception as e:
        logger.error(f"Safe evaluate error for expression: {expression[:100]}... - Error: {e}")
        return None