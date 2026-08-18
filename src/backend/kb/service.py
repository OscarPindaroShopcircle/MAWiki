from sqlalchemy.ext.asyncio import AsyncSession


class KbService:
    """ """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_sample(self) -> None:
        return None
