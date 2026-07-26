"""用户记忆设置和显式记忆CRUD。"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db_session
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import UserResponse
from app.modules.memory.schemas import MemorySettingResponse, MemorySettingUpdate, UserMemoryListResponse, UserMemoryResponse, UserMemoryWrite
from app.modules.memory.service import UserMemoryService

router = APIRouter(prefix="/profile", tags=["用户记忆"])


def get_user_memory_service(session: Session = Depends(get_db_session)):
    return UserMemoryService(session)


@router.get("/memory-settings", response_model=MemorySettingResponse)
def get_setting(current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    return service.get_setting(current_user.id)


@router.put("/memory-settings", response_model=MemorySettingResponse)
def update_setting(payload: MemorySettingUpdate, current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    return service.update_setting(current_user.id, payload.enabled)


@router.get("/memories", response_model=UserMemoryListResponse)
def list_memories(current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    return service.list(current_user.id)


@router.post("/memories", response_model=UserMemoryResponse, status_code=201)
def create_memory(payload: UserMemoryWrite, current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    return service.create(current_user.id, payload)


@router.put("/memories/{memory_id}", response_model=UserMemoryResponse)
def update_memory(memory_id: str, payload: UserMemoryWrite, current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    return service.update(current_user.id, memory_id, payload)


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: str, current_user: UserResponse = Depends(get_current_user), service: UserMemoryService = Depends(get_user_memory_service)):
    service.delete(current_user.id, memory_id)
    return Response(status_code=204)
