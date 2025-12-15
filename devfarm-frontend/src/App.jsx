import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import LoginPage from './pages/Login.jsx'
import Home from './pages/Home.jsx'
import DeviceAndroid from './pages/DeviceAndroid.jsx'
import DeviceIos from './pages/DeviceIos.jsx'
import Builds from './pages/Builds.jsx'

function NavBar() {
  const navigate = useNavigate()
  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-white">
      <div className="text-lg font-semibold">Device Manager</div>
      <div className="flex gap-2">
        <button className="px-3 py-2 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-50" onClick={() => navigate('/')}>Home</button>
        <button className="px-3 py-2 rounded-md border cursor-pointer bg-white text-gray-800 border-gray-300 hover:bg-gray-50" onClick={() => navigate('/builds')}>Builds</button>
      </div>
    </div>
  )
}

function App() {
  const [authed, setAuthed] = useState(false)
  useEffect(() => {
    (async () => {
      try {
        const BACKEND = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
        const res = await fetch(`${BACKEND}/gitlab/user`, { credentials: 'include' })
        if (!res.ok) throw new Error(`status ${res.status}`)
        setAuthed(true)
      } catch {
        setAuthed(false)
      }
    })()
  }, [])
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50 text-gray-900">
        <NavBar />
        <div className="p-4">
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={authed ? <Home /> : <LoginPage />} />
            <Route path="/builds" element={authed ? <Builds /> : <LoginPage />} />
            <Route path="/device/android/:avdName" element={authed ? <DeviceAndroid /> : <LoginPage />} />
            <Route path="/device/ios/:udid" element={authed ? <DeviceIos /> : <LoginPage />} />
          </Routes>
        </div>
      </div>
    </BrowserRouter>
  )
}


export default App