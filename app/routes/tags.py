"""Tag management API endpoints.

Provides CRUD operations for tags and prompt-tag associations.
Tags are used for access control - controlling which prompts can be sent to which LLM models.
"""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime

from backend.database import get_db, Tag, PromptTag, Prompt, SystemSetting

router = APIRouter()


# ========== Pydantic Models ==========

class TagCreate(BaseModel):
    """Request to create a new tag."""
    name: str
    color: str = "#6b7280"
    description: Optional[str] = None


class TagUpdate(BaseModel):
    """Request to update a tag."""
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None


class TagResponse(BaseModel):
    """Tag response model."""
    id: int
    name: str
    color: str
    description: Optional[str]
    is_system: bool
    created_at: str
    prompt_count: int = 0


class PromptTagsUpdate(BaseModel):
    """Request to update prompt tags."""
    tag_ids: List[int]


class ModelTagsUpdate(BaseModel):
    """Request to update model allowed tags."""
    tag_ids: List[int]


class ModelTagsResponse(BaseModel):
    """Model allowed tags response."""
    model_name: str
    allowed_tag_ids: List[int]
    allowed_tags: List[TagResponse]


# ========== Tag CRUD Endpoints ==========

@router.get("/api/tags", response_model=List[TagResponse])
def list_tags(db: Session = Depends(get_db)):
    """List all tags.

    Returns all tags with their usage count (number of prompts using each tag).
    """
    tags = db.query(Tag).order_by(Tag.name).all()

    result = []
    for tag in tags:
        prompt_count = db.query(PromptTag).filter(PromptTag.tag_id == tag.id).count()
        result.append(TagResponse(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            description=tag.description,
            is_system=bool(tag.is_system),
            created_at=tag.created_at,
            prompt_count=prompt_count
        ))

    return result


@router.post("/api/tags", response_model=TagResponse)
def create_tag(request: TagCreate, db: Session = Depends(get_db)):
    """Create a new tag.

    Tag names must be unique (case-insensitive).
    """
    # Check for duplicate name
    existing = db.query(Tag).filter(Tag.name.ilike(request.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Tag '{request.name}' already exists")

    tag = Tag(
        name=request.name,
        color=request.color,
        description=request.description,
        is_system=0,
        created_at=datetime.utcnow().isoformat()
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)

    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        is_system=False,
        created_at=tag.created_at,
        prompt_count=0
    )


@router.get("/api/tags/{tag_id}", response_model=TagResponse)
def get_tag(tag_id: int, db: Session = Depends(get_db)):
    """Get a specific tag."""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    prompt_count = db.query(PromptTag).filter(PromptTag.tag_id == tag.id).count()

    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        is_system=bool(tag.is_system),
        created_at=tag.created_at,
        prompt_count=prompt_count
    )


@router.put("/api/tags/{tag_id}", response_model=TagResponse)
def update_tag(tag_id: int, request: TagUpdate, db: Session = Depends(get_db)):
    """Update a tag.

    System tags (like "ALL") can only have their color and description updated.
    """
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Check for duplicate name if name is being changed
    if request.name and request.name != tag.name:
        if tag.is_system:
            raise HTTPException(status_code=400, detail="Cannot rename system tag")

        existing = db.query(Tag).filter(
            Tag.name.ilike(request.name),
            Tag.id != tag_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Tag '{request.name}' already exists")
        tag.name = request.name

    if request.color:
        tag.color = request.color
    if request.description is not None:
        tag.description = request.description

    db.commit()
    db.refresh(tag)

    prompt_count = db.query(PromptTag).filter(PromptTag.tag_id == tag.id).count()

    return TagResponse(
        id=tag.id,
        name=tag.name,
        color=tag.color,
        description=tag.description,
        is_system=bool(tag.is_system),
        created_at=tag.created_at,
        prompt_count=prompt_count
    )


@router.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """Delete a tag.

    System tags (like "ALL") cannot be deleted.
    Deleting a tag will remove it from all prompts.
    """
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    if tag.is_system:
        raise HTTPException(status_code=400, detail="Cannot delete system tag")

    # Delete all prompt-tag associations
    db.query(PromptTag).filter(PromptTag.tag_id == tag_id).delete()

    # Delete the tag
    db.delete(tag)
    db.commit()

    return {"success": True, "message": f"Tag '{tag.name}' deleted"}


# ========== Prompt-Tag Association Endpoints ==========

@router.get("/api/prompts/{prompt_id}/tags", response_model=List[TagResponse])
def get_prompt_tags(prompt_id: int, db: Session = Depends(get_db)):
    """Get all tags for a prompt.

    Returns the "ALL" tag if prompt has no tags (backward compatibility).
    """
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    prompt_tags = db.query(PromptTag).filter(PromptTag.prompt_id == prompt_id).all()

    # If no tags, return "ALL" tag (backward compatibility)
    if not prompt_tags:
        all_tag = db.query(Tag).filter(Tag.name == "ALL").first()
        if all_tag:
            return [TagResponse(
                id=all_tag.id,
                name=all_tag.name,
                color=all_tag.color,
                description=all_tag.description,
                is_system=True,
                created_at=all_tag.created_at,
                prompt_count=0
            )]
        return []

    result = []
    for pt in prompt_tags:
        tag = pt.tag
        result.append(TagResponse(
            id=tag.id,
            name=tag.name,
            color=tag.color,
            description=tag.description,
            is_system=bool(tag.is_system),
            created_at=tag.created_at,
            prompt_count=0
        ))

    return result


@router.put("/api/prompts/{prompt_id}/tags", response_model=List[TagResponse])
def update_prompt_tags(prompt_id: int, request: PromptTagsUpdate, db: Session = Depends(get_db)):
    """Update tags for a prompt.

    Replaces all existing tags with the provided list.
    """
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Remove all existing tags
    db.query(PromptTag).filter(PromptTag.prompt_id == prompt_id).delete()

    # Add new tags
    for tag_id in request.tag_ids:
        tag = db.query(Tag).filter(Tag.id == tag_id).first()
        if tag:
            prompt_tag = PromptTag(
                prompt_id=prompt_id,
                tag_id=tag_id,
                created_at=datetime.utcnow().isoformat()
            )
            db.add(prompt_tag)

    db.commit()

    # Return updated tags
    return get_prompt_tags(prompt_id, db)


@router.post("/api/prompts/{prompt_id}/tags/{tag_id}")
def add_tag_to_prompt(prompt_id: int, tag_id: int, db: Session = Depends(get_db)):
    """Add a single tag to a prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")

    # Check if already assigned
    existing = db.query(PromptTag).filter(
        PromptTag.prompt_id == prompt_id,
        PromptTag.tag_id == tag_id
    ).first()

    if existing:
        return {"message": "Tag already assigned", "prompt_id": prompt_id, "tag_id": tag_id}

    # Add the tag
    prompt_tag = PromptTag(
        prompt_id=prompt_id,
        tag_id=tag_id,
        created_at=datetime.utcnow().isoformat()
    )
    db.add(prompt_tag)
    db.commit()

    return {"message": "Tag added successfully", "prompt_id": prompt_id, "tag_id": tag_id}


@router.delete("/api/prompts/{prompt_id}/tags/{tag_id}")
def remove_tag_from_prompt(prompt_id: int, tag_id: int, db: Session = Depends(get_db)):
    """Remove a single tag from a prompt."""
    prompt = db.query(Prompt).filter(Prompt.id == prompt_id).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt not found")

    # Find and delete the prompt-tag relationship
    prompt_tag = db.query(PromptTag).filter(
        PromptTag.prompt_id == prompt_id,
        PromptTag.tag_id == tag_id
    ).first()

    if not prompt_tag:
        return {"message": "Tag not assigned to prompt", "prompt_id": prompt_id, "tag_id": tag_id}

    db.delete(prompt_tag)
    db.commit()

    return {"message": "Tag removed successfully", "prompt_id": prompt_id, "tag_id": tag_id}


# ========== Model-Tag Configuration Endpoints ==========

def get_model_allowed_tags_setting(model_name: str, db: Session) -> List[int]:
    """Get allowed tag IDs for a model from system settings."""
    setting_key = f"model_allowed_tags_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    if not setting or not setting.value:
        # Default: only "ALL" tag is allowed
        all_tag = db.query(Tag).filter(Tag.name == "ALL").first()
        return [all_tag.id] if all_tag else []

    try:
        return json.loads(setting.value)
    except json.JSONDecodeError:
        return []


def set_model_allowed_tags_setting(model_name: str, tag_ids: List[int], db: Session):
    """Set allowed tag IDs for a model in system settings."""
    setting_key = f"model_allowed_tags_{model_name}"
    setting = db.query(SystemSetting).filter(SystemSetting.key == setting_key).first()

    if setting:
        setting.value = json.dumps(tag_ids)
    else:
        setting = SystemSetting(key=setting_key, value=json.dumps(tag_ids))
        db.add(setting)

    db.commit()


@router.get("/api/models/{model_name}/tags", response_model=ModelTagsResponse)
def get_model_allowed_tags(model_name: str, db: Session = Depends(get_db)):
    """Get allowed tags for a model.

    Default: only "ALL" tag is allowed.
    """
    tag_ids = get_model_allowed_tags_setting(model_name, db)

    tags = []
    for tag_id in tag_ids:
        tag = db.query(Tag).filter(Tag.id == tag_id).first()
        if tag:
            tags.append(TagResponse(
                id=tag.id,
                name=tag.name,
                color=tag.color,
                description=tag.description,
                is_system=bool(tag.is_system),
                created_at=tag.created_at,
                prompt_count=0
            ))

    return ModelTagsResponse(
        model_name=model_name,
        allowed_tag_ids=tag_ids,
        allowed_tags=tags
    )


@router.put("/api/models/{model_name}/tags", response_model=ModelTagsResponse)
def update_model_allowed_tags(model_name: str, request: ModelTagsUpdate, db: Session = Depends(get_db)):
    """Update allowed tags for a model.

    Replaces all existing allowed tags with the provided list.
    """
    # Validate tag IDs
    valid_tag_ids = []
    for tag_id in request.tag_ids:
        tag = db.query(Tag).filter(Tag.id == tag_id).first()
        if tag:
            valid_tag_ids.append(tag_id)

    set_model_allowed_tags_setting(model_name, valid_tag_ids, db)

    return get_model_allowed_tags(model_name, db)


# ========== Tag Validation ==========

def validate_prompt_tags_for_model(prompt_id: int, model_name: str, db: Session) -> tuple[bool, str]:
    """Validate if a prompt can be executed on a model based on tags.

    Returns:
        tuple: (is_valid, error_message)
        - is_valid: True if prompt tags match model's allowed tags
        - error_message: Description if validation fails

    Rules:
    - Prompt with no tags is treated as having "ALL" tag (backward compatibility)
    - Model with no allowed tags setting is treated as allowing "ALL" tag only
    - If ANY of the prompt's tags match ANY of the model's allowed tags, validation passes
    """
    # Get prompt tags (or "ALL" if none)
    prompt_tag_ids = set()
    prompt_tags = db.query(PromptTag).filter(PromptTag.prompt_id == prompt_id).all()

    if prompt_tags:
        prompt_tag_ids = {pt.tag_id for pt in prompt_tags}
    else:
        # No tags = "ALL" tag (backward compatibility)
        all_tag = db.query(Tag).filter(Tag.name == "ALL").first()
        if all_tag:
            prompt_tag_ids = {all_tag.id}

    # Get model allowed tags (or "ALL" if not configured)
    model_tag_ids = set(get_model_allowed_tags_setting(model_name, db))

    # Check intersection
    if prompt_tag_ids & model_tag_ids:
        return True, ""

    # Get tag names for error message
    prompt_tag_names = []
    for tag_id in prompt_tag_ids:
        tag = db.query(Tag).filter(Tag.id == tag_id).first()
        if tag:
            prompt_tag_names.append(tag.name)

    model_tag_names = []
    for tag_id in model_tag_ids:
        tag = db.query(Tag).filter(Tag.id == tag_id).first()
        if tag:
            model_tag_names.append(tag.name)

    error_msg = (
        f"タグ制限エラー: プロンプトのタグ [{', '.join(prompt_tag_names)}] は "
        f"モデル '{model_name}' の許可タグ [{', '.join(model_tag_names)}] と一致しません / "
        f"Tag restriction: Prompt tags [{', '.join(prompt_tag_names)}] do not match "
        f"model '{model_name}' allowed tags [{', '.join(model_tag_names)}]"
    )

    return False, error_msg


@router.get("/api/validate-tags")
def validate_tags_endpoint(prompt_id: int, model_name: str, db: Session = Depends(get_db)):
    """API endpoint to validate prompt tags against model.

    Query params:
        - prompt_id: ID of the prompt
        - model_name: Name of the LLM model

    Returns validation result.
    """
    is_valid, error_msg = validate_prompt_tags_for_model(prompt_id, model_name, db)

    return {
        "valid": is_valid,
        "error": error_msg if not is_valid else None
    }
