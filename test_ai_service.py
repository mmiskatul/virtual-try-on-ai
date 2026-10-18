import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    import asyncio
    from tests.test_ai_service import run_tests
    asyncio.run(run_tests())
