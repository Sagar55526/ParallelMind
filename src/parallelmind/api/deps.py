from fastapi import Request

from parallelmind.storage.task_repo import TaskRepo


async def get_repo(request: Request):
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield TaskRepo(session)


def get_queue(request: Request):
    return request.app.state.queue
