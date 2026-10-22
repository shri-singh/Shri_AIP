"""Speech abstraction only; implement enterprise Transcribe/Polly adapters later."""
from typing import Protocol
class Transcriber(Protocol):
    async def transcribe(self,audio:bytes,mime_type:str,locale:str)->str: ...
class Synthesizer(Protocol):
    async def synthesize(self,text:str,voice_id:str,locale:str)->bytes: ...
# No automatic microphone capture, audio retention or recording by default.
