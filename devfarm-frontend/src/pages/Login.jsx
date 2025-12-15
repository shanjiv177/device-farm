import React from 'react'

export default function LoginPage() {
  const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
  return (
    <div className="max-w-lg mx-auto bg-white border border-gray-200 rounded-lg p-6">
      <h2 className="text-xl font-semibold mb-2">Login Required</h2>
      <p className="text-sm text-gray-600 mb-4">
        You’re not authenticated. Login with GitLab to continue.
      </p>
      <a
        href={`${BACKEND}/login`}
        className="inline-block px-4 py-2 rounded-md border cursor-pointer bg-blue-600 text-white border-blue-600"
      >
        Login with GitLab
      </a>
    </div>
  )
}
