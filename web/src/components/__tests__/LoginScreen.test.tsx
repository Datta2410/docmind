import { render, screen } from "@testing-library/react"
import { describe, it, expect } from "vitest"
import { LoginScreen } from "../LoginScreen"

describe("LoginScreen", () => {
  it("shows the product name and three OAuth buttons", () => {
    render(<LoginScreen />)
    expect(screen.getByText(/YDG DocMind/i)).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /Google/i }))
      .toHaveAttribute("href", "/api/auth/google/login")
    expect(screen.getByRole("link", { name: /GitHub/i }))
      .toHaveAttribute("href", "/api/auth/github/login")
    expect(screen.getByRole("link", { name: /Twitter/i }))
      .toHaveAttribute("href", "/api/auth/twitter/login")
  })
})
