from pydantic import BaseModel, Field, field_validator, model_validator


class CustomerRegistrationRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    age: int = Field(ge=13, le=120)
    reason: str = Field(min_length=2, max_length=1000)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str | None = Field(default=None, min_length=8, max_length=128)
    widget_key: str = Field(min_length=12, max_length=256)

    @field_validator("full_name", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be empty.")
        return value

    @model_validator(mode="after")
    def check_passwords_match(self):
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match.")
        return self


class CustomerLoginRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    customer_id: str = Field(pattern=r"^BI-\d{6,}$", max_length=32)
    password: str = Field(min_length=8, max_length=128)
    widget_key: str = Field(min_length=12, max_length=256)

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name cannot be empty.")
        return value
